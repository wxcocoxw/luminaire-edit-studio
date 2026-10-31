#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run an API-format ComfyUI generation or upscaling template over a folder.

Python 3.10+; standard library only. This program never installs software,
starts ComfyUI, changes source files, or cancels server-side jobs.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import fnmatch
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


SCHEMA_VERSION = 1
MAX_SEED = (1 << 63) - 1
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
FAILED_STATES = {"failed", "completed_no_output", "invalid"}
UNFINISHED_STATES = {"submitting", "submission_unknown", "queued", "running"}
POSTPROCESS_PREFIX = "__qwen_post_"
POSTPROCESS_VERSION = "native-upscale-grain-v1"


class BatchError(Exception):
    """A user-actionable configuration or job error."""


class TransportError(BatchError):
    """A request may not have received a response."""


class ServerError(BatchError):
    """The server returned an explicit HTTP error."""


class PendingJob(BatchError):
    """An accepted or possibly accepted job is not known to be terminal."""


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def read_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError) as exc:
        raise BatchError(f"Cannot read JSON {path}: {exc}") from exc


def atomic_json(path, value):
    """Replace a manifest only after its complete replacement is on disk."""
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


@contextlib.contextmanager
def state_lock(directory):
    """OS-managed lock: a crashed process cannot leave a permanent stale lock."""
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / "run.lock").open("a+b")
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BatchError(f"Another batch runner is using {directory}.") from exc
        yield
    finally:
        stream.close()


def natural_key(path):
    text = path.as_posix() if isinstance(path, Path) else str(path)
    parts = tuple((0, int(p)) if p.isdigit() else (1, p.casefold())
                  for p in re.split(r"(\d+)", text))
    return parts, text.casefold(), text


def safe_component(text):
    # Keep readable basenames, while avoiding traversal and Windows punctuation.
    text = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", text).strip(" .")
    text = text or "image"
    if text.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                        *(f"LPT{i}" for i in range(1, 10))}:
        text = "_" + text
    return text[:100]


def safe_subfolder(value):
    value = value.replace("\\", "/")
    if value.startswith("/"):
        raise BatchError("Output subfolder must be relative to the ComfyUI output directory.")
    value = value.rstrip("/")
    if not value or any(p in {"", ".", ".."} for p in value.split("/")) or ":" in value:
        raise BatchError("Output subfolder must be a relative folder without '..' or drive letters.")
    return "/".join(safe_component(p) for p in value.split("/"))


def validate_binding(template, binding, label, string=True):
    if not isinstance(binding, dict) or not all(k in binding for k in ("node_id", "input")):
        raise BatchError(f"Mapping {label} needs node_id and input.")
    node_id, field = str(binding["node_id"]), binding["input"]
    if node_id not in template or not isinstance(field, str):
        raise BatchError(f"Mapping {label} points to an unknown node or input: {node_id}.{field}")
    inputs = template[node_id]["inputs"]
    if field not in inputs:
        raise BatchError(f"Mapping {label} input does not exist: {node_id}.{field}")
    current = inputs[field]
    if string and not isinstance(current, str):
        raise BatchError(f"Mapping {label} must target a literal string input, not a connected socket.")
    if not string and (not isinstance(current, int) or isinstance(current, bool)):
        raise BatchError(f"Mapping {label} must target a literal integer seed input.")
    return {**binding, "node_id": node_id}


def validate_template(template, mapping):
    if isinstance(template, dict) and "prompt" in template and isinstance(template["prompt"], dict):
        template = template["prompt"]
    if not isinstance(template, dict) or not template or "nodes" in template:
        raise BatchError("Template must be ComfyUI API-format JSON, not a canvas/workflow JSON.")
    for node_id, node in template.items():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            raise BatchError(f"Invalid API node {node_id!r}; expected class_type and inputs.")
    if not isinstance(mapping, dict) or mapping.get("version") not in (1, 2):
        raise BatchError("Mapping JSON must have version: 1 or 2.")
    result = copy.deepcopy(mapping)
    task = mapping.get("task", "generate")
    if mapping["version"] == 2 and task not in ("generate", "upscale"):
        raise BatchError("Mapping task must be 'generate' or 'upscale'.")
    if mapping["version"] == 1 and (task != "generate" or "postprocess" in mapping):
        raise BatchError("Pure upscaling and postprocessing require a version 2 mapping.")
    if mapping["version"] == 2:
        if "task" not in mapping:
            raise BatchError("Version 2 mappings must explicitly name task: 'generate' or 'upscale'.")
        result["task"] = task
    if task == "upscale" and any(role in mapping for role in ("prompt", "seed", "mask")):
        raise BatchError("An upscale task must omit generation prompt, seed, and mask bindings.")
    required_roles = ("source", "prompt", "seed", "save") if task == "generate" else ("source", "save")
    for role in required_roles:
        if role not in mapping:
            raise BatchError(f"Mapping is missing {role}.")
        result[role] = validate_binding(template, mapping[role], role, string=role != "seed")
    for role in ("additional_saves", "references"):
        values = mapping.get(role, [])
        if not isinstance(values, list):
            raise BatchError(f"Mapping {role} must be an array.")
        result[role] = [validate_binding(template, value, f"{role}[{i}]")
                        for i, value in enumerate(values)]
    suffixes = set()
    for save in result["additional_saves"]:
        suffix = save.get("suffix")
        if not isinstance(suffix, str) or not suffix or safe_component(suffix) != suffix or suffix in suffixes:
            raise BatchError("Each additional save needs a distinct, filename-safe, nonempty suffix.")
        suffixes.add(suffix)
    if "mask" in mapping:
        result["mask"] = validate_binding(template, mapping["mask"], "mask")
        if mapping["mask"].get("semantics", "white-edit") != "white-edit":
            raise BatchError("Separate masks use white-edit semantics; invert upstream explicitly if needed.")
    if task == "upscale" and result["references"]:
        raise BatchError("An upscale task cannot contain reference bindings.")
    bindings = [result[role] for role in required_roles]
    bindings += result["additional_saves"] + result["references"]
    if "mask" in result:
        bindings.append(result["mask"])
    targets = [(b["node_id"], b["input"]) for b in bindings]
    if len(targets) != len(set(targets)):
        raise BatchError("Two mapping roles target the same input.")
    if "postprocess" in mapping:
        result["postprocess"] = validate_postprocess_mapping(template, mapping["postprocess"], task, targets)
    elif task == "upscale":
        raise BatchError("An upscale task requires a postprocess attachment in its mapping.")
    return copy.deepcopy(template), result


def validate_postprocess_mapping(template, value, task, other_targets):
    if not isinstance(value, dict):
        raise BatchError("Mapping postprocess must be an object.")
    anchor = value.get("input")
    if (not isinstance(anchor, list) or len(anchor) != 2 or str(anchor[0]) not in template
            or not isinstance(anchor[1], int) or isinstance(anchor[1], bool) or anchor[1] < 0):
        raise BatchError("postprocess.input must be an existing [node_id, nonnegative_output_slot] image link.")
    anchor = [str(anchor[0]), anchor[1]]
    if any(node_id.startswith(POSTPROCESS_PREFIX) for node_id in template):
        raise BatchError(f"Template node IDs beginning with {POSTPROCESS_PREFIX!r} are reserved for the batch runner.")
    targets = value.get("targets")
    if not isinstance(targets, list) or not targets:
        raise BatchError("postprocess.targets must contain at least one existing image input.")
    normalized = []
    seen = set(other_targets)
    for target in targets:
        if not isinstance(target, dict) or not isinstance(target.get("input"), str):
            raise BatchError("Each postprocess target needs node_id and input.")
        node_id, field = str(target.get("node_id")), target["input"]
        if node_id not in template or field not in template[node_id]["inputs"]:
            raise BatchError(f"Unknown postprocess target: {node_id}.{field}")
        current = template[node_id]["inputs"][field]
        if (not isinstance(current, list) or len(current) != 2
                or [str(current[0]), current[1]] != anchor):
            raise BatchError(f"postprocess target {node_id}.{field} must already connect to postprocess.input.")
        if (node_id, field) in seen:
            raise BatchError("A postprocess target duplicates another mapped input.")
        seen.add((node_id, field))
        normalized.append({"node_id": node_id, "input": field})
    defaults = {"upscale": "lanczos" if task == "upscale" else "off", "scale": 2.0,
                "upscale_model": None, "grain": 0.0, "grain_seed": 42}
    supplied = value.get("defaults", {})
    if not isinstance(supplied, dict) or any(key not in defaults for key in supplied):
        raise BatchError("Unknown postprocess default; supported keys are upscale, scale, upscale_model, grain, grain_seed.")
    defaults.update(supplied)
    validate_postprocess_settings(defaults, require_model=False)
    return {**value, "input": anchor, "targets": normalized, "defaults": defaults}


def validate_postprocess_settings(settings, require_model=True):
    if settings["upscale"] not in ("off", "lanczos", "ai"):
        raise BatchError("Upscale mode must be off, lanczos, or ai.")
    for key, minimum, maximum in (("scale", 1.0, 8.0), ("grain", 0.0, 1.0)):
        value = settings[key]
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or not minimum <= value <= maximum):
            raise BatchError(f"{key} must be a finite number from {minimum:g} to {maximum:g}.")
    seed = settings["grain_seed"]
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= MAX_SEED:
        raise BatchError("grain_seed must be a nonnegative signed 64-bit integer.")
    model = settings["upscale_model"]
    if model is not None and not isinstance(model, str):
        raise BatchError("upscale_model must be a model filename or null.")
    if require_model and settings["upscale"] == "ai" and (not model or not model.strip() or model.startswith("REPLACE_")):
        raise BatchError("AI upscaling requires --upscale-model or a real upscale_model default in the mapping.")


def resolve_postprocess(args, mapping):
    keys = ("upscale", "scale", "upscale_model", "grain", "grain_seed")
    if "postprocess" not in mapping:
        if any(getattr(args, key) is not None for key in keys):
            raise BatchError("Processing flags require a version 2 mapping with a postprocess attachment.")
        return None
    settings = dict(mapping["postprocess"]["defaults"])
    settings.update({key: getattr(args, key) for key in keys if getattr(args, key) is not None})
    validate_postprocess_settings(settings)
    if args.upscale_model is not None and settings["upscale"] != "ai":
        raise BatchError("--upscale-model requires --upscale ai.")
    if args.scale is not None and settings["upscale"] == "off":
        raise BatchError("--scale requires --upscale lanczos or ai; use --grain alone for grain without resizing.")
    settings["scale"] = float(settings["scale"])
    settings["grain"] = float(settings["grain"])
    if settings["upscale_model"] is not None:
        settings["upscale_model"] = settings["upscale_model"].strip()
    settings["pipeline_version"] = POSTPROCESS_VERSION
    if mapping.get("task") == "upscale":
        if settings["upscale"] == "off" and settings["grain"] == 0:
            raise BatchError("Pure processing needs an upscale mode or nonzero grain; off with zero grain is a no-op.")
        if args.variants > 1 and settings["grain"] == 0:
            raise BatchError("Pure upscaling without grain is deterministic; use --variants 1 to avoid identical copies.")
    return settings


def inject_postprocess(graph, mapping, settings, grain_seed):
    """Attach only the requested native processing nodes to explicit API links."""
    if settings is None:
        return
    source = mapping["postprocess"]["input"]
    current = list(source)

    def add(name, class_type, inputs):
        node_id = POSTPROCESS_PREFIX + name
        if node_id in graph:
            raise BatchError(f"Reserved processing node already exists: {node_id}")
        graph[node_id] = {"class_type": class_type, "inputs": inputs}
        return [node_id, 0]

    if settings["upscale"] == "lanczos":
        current = add("resize", "ImageScaleBy", {"image": current, "upscale_method": "lanczos", "scale_by": settings["scale"]})
    elif settings["upscale"] == "ai":
        model = add("model", "UpscaleModelLoader", {"model_name": settings["upscale_model"]})
        current = add("ai", "ImageUpscaleWithModel", {"upscale_model": model, "image": current})
        size = add("size", "GetImageSize", {"image": list(source)})
        width = add("width", "ComfyMathExpression", {"expression": "max(1, round(a * b))",
                    "values.a": [size[0], 0], "values.b": settings["scale"]})
        height = add("height", "ComfyMathExpression", {"expression": "max(1, round(a * b))",
                     "values.a": [size[0], 1], "values.b": settings["scale"]})
        current = add("resize", "ImageScale", {"image": current, "upscale_method": "lanczos",
                      "width": [width[0], 1], "height": [height[0], 1], "crop": "disabled"})
    if settings["grain"] > 0:
        if grain_seed is None:
            raise BatchError("The job has no recorded grain seed.")
        current = add("grain", "ImageAddNoise", {"image": current, "seed": grain_seed, "strength": settings["grain"]})
    for target in mapping["postprocess"]["targets"]:
        put_value(graph, target, list(current))


def get_value(template, binding):
    return template[binding["node_id"]]["inputs"][binding["input"]]


def put_value(template, binding, value):
    template[binding["node_id"]]["inputs"][binding["input"]] = value


def image_info(path):
    """Read common still-image headers; do not decode or modify the image."""
    with path.open("rb") as stream:
        header = stream.read(32)
        if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 26:
            width, height = struct.unpack(">II", header[16:24])
            alpha = header[25] in (4, 6)
            stream.seek(8)
            while not alpha:
                chunk = stream.read(8)
                if len(chunk) != 8:
                    break
                length, kind = struct.unpack(">I4s", chunk)
                if kind == b"tRNS":
                    alpha = True
                    break
                if kind in (b"IDAT", b"IEND"):
                    break
                stream.seek(length + 4, os.SEEK_CUR)
            return width, height, alpha
        if header.startswith(b"\xff\xd8"):
            stream.seek(2)
            while True:
                marker = stream.read(1)
                if not marker:
                    break
                if marker != b"\xff":
                    continue
                marker = stream.read(1)
                while marker == b"\xff":
                    marker = stream.read(1)
                if not marker or marker[0] in (0xD9, 0xDA):
                    break
                if marker[0] in (0xD8, 0x01, *range(0xD0, 0xD8)):
                    continue
                length_bytes = stream.read(2)
                if len(length_bytes) != 2:
                    break
                length = struct.unpack(">H", length_bytes)[0]
                if length < 2:
                    break
                if marker[0] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    frame = stream.read(5)
                    if len(frame) == 5:
                        height, width = struct.unpack(">HH", frame[1:])
                        return width, height, False
                    break
                stream.seek(length - 2, os.SEEK_CUR)
        if header[:2] == b"BM" and len(header) >= 26:
            width, height = struct.unpack("<ii", header[18:26])
            return abs(width), abs(height), None
        if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
            kind = header[12:16]
            if kind == b"VP8X" and len(header) >= 30:
                return (int.from_bytes(header[24:27], "little") + 1,
                        int.from_bytes(header[27:30], "little") + 1, bool(header[20] & 16))
            if kind == b"VP8 " and len(header) >= 30 and header[23:26] == b"\x9d\x01\x2a":
                width, height = struct.unpack("<HH", header[26:30])
                return width & 0x3FFF, height & 0x3FFF, False
            if kind == b"VP8L" and len(header) >= 25 and header[20] == 0x2F:
                bits = int.from_bytes(header[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1, bool(bits & (1 << 28))
    raise BatchError(f"Cannot verify image dimensions for {path.name}; use PNG/JPEG/BMP/WebP for mask matching.")


def seed_for(mode, base, relative, variant):
    if mode == "fixed":
        return (base + variant - 1) & MAX_SEED
    if mode == "stable-per-source":
        return int(digest([base, relative, variant])[:16], 16) & MAX_SEED
    return None


def build_plan(args, template, mapping):
    generation = mapping.get("task", "generate") == "generate"
    postprocess = resolve_postprocess(args, mapping)
    if not generation:
        if (args.prompt is not None or args.prompt_file or args.sidecar_prompts or args.sidecar_dir
                or args.require_sidecars or args.prompt_prefix or args.prompt_suffix):
            raise BatchError("Pure upscaling does not use prompts or prompt sidecars; omit those options.")
        if args.generation_seed_options_explicit:
            raise BatchError("Pure upscaling has no generation seed; use --grain-seed for deterministic grain.")
        if args.mask_mode != "none" or args.mask_dir or args.mask_suffix or args.reference:
            raise BatchError("Pure upscaling does not use edit masks or reference images; source alpha is preserved by its template.")
    input_dir = Path(args.input_dir).expanduser().resolve()
    if not input_dir.is_dir():
        raise BatchError(f"Input folder does not exist: {input_dir}")
    mask_dir = Path(args.mask_dir).expanduser().resolve() if args.mask_dir else None
    if args.mask_mode == "separate":
        if mask_dir is None or not mask_dir.is_dir() or "mask" not in mapping:
            raise BatchError("Separate masks require --mask-dir and a mapping.mask input.")
    elif mask_dir is not None:
        raise BatchError("--mask-dir requires --mask-mode separate.")
    if args.mask_mode != "separate" and "mask" in mapping:
        raise BatchError("This mapping has a separate mask loader; use --mask-mode separate or an alpha/unmasked template.")
    prompt_root = Path(args.sidecar_dir).expanduser().resolve() if args.sidecar_dir else input_dir
    if args.sidecar_dir and not args.sidecar_prompts:
        raise BatchError("--sidecar-dir requires --sidecar-prompts.")
    if args.require_sidecars and not args.sidecar_prompts:
        raise BatchError("--require-sidecars requires --sidecar-prompts.")
    if args.prompt is not None and args.prompt_file:
        raise BatchError("Choose --prompt or --prompt-file, not both.")
    shared_prompt = (args.prompt if args.prompt is not None else get_value(template, mapping["prompt"])) if generation else ""
    if args.prompt_file:
        shared_prompt = Path(args.prompt_file).expanduser().read_text(encoding="utf-8-sig")
    references = []
    if len(args.reference) != len(mapping["references"]):
        raise BatchError(f"This mapping needs exactly {len(mapping['references'])} --reference file(s); "
                         f"{len(args.reference)} were supplied. For static server references, "
                         "omit their loaders from mapping.references.")
    for path_text in args.reference:
        path = Path(path_text).expanduser().resolve()
        if not path.is_file():
            raise BatchError(f"Reference image does not exist: {path}")
        references.append({"path": path, "sha256": file_hash(path), "name": path.name})
    candidates = input_dir.rglob("*") if args.recursive else input_dir.iterdir()
    files = []
    for path in candidates:
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        # Avoid following image symlinks outside the declared source tree.
        if not path.resolve().is_relative_to(input_dir):
            continue
        if mask_dir is not None and path.resolve().is_relative_to(mask_dir):
            continue
        relative = path.relative_to(input_dir).as_posix()
        if any(fnmatch.fnmatchcase(relative, pattern) for pattern in args.exclude):
            continue
        files.append(path)
    files.sort(key=lambda p: natural_key(p.relative_to(input_dir)))
    files = files[args.start:None if args.limit is None else args.start + args.limit]
    if not files:
        raise BatchError("No source images matched the folder, range and filters.")
    config = {
        "template": template, "mapping": mapping, "server": args.server,
        "input_dir": str(input_dir), "recursive": args.recursive, "exclude": args.exclude,
        "start": args.start, "limit": args.limit, "variants": args.variants,
        "seed_mode": args.seed_mode if generation else None, "seed": args.seed if generation else None,
        "shared_prompt": shared_prompt,
        "prompt_prefix": args.prompt_prefix, "prompt_suffix": args.prompt_suffix,
        "sidecar_prompts": args.sidecar_prompts, "require_sidecars": args.require_sidecars,
        "sidecar_dir": str(prompt_root), "mask_mode": args.mask_mode,
        "mask_dir": str(mask_dir) if mask_dir else None, "mask_suffix": args.mask_suffix,
        "references": [{k: r[k] for k in ("sha256", "name")} for r in references],
        "output_subfolder": args.output_subfolder,
    }
    if postprocess is not None:
        config["postprocess"] = postprocess
    fingerprint = digest(config)
    jobs = []
    for path in files:
        relative_path = path.relative_to(input_dir)
        relative = relative_path.as_posix()
        source_hash, mask_hash, mask_path, preflight_error = None, None, None, None
        body = shared_prompt
        try:
            source_hash = file_hash(path)
            if args.sidecar_prompts:
                sidecar = (prompt_root / relative_path).with_suffix(".txt")
                if sidecar.is_file():
                    body = sidecar.read_text(encoding="utf-8-sig")
                elif args.require_sidecars:
                    raise BatchError(f"Missing prompt sidecar: {sidecar}")
            if args.mask_mode == "alpha":
                if path.suffix.lower() != ".png" or not image_info(path)[2]:
                    raise BatchError("Alpha mask mode requires a PNG carrying alpha and a template wired to use the source alpha mask.")
            elif args.mask_mode == "separate":
                mask_path = mask_dir / relative_path.parent / (relative_path.stem + args.mask_suffix + ".png")
                if not mask_path.is_file():
                    raise BatchError(f"Missing mask: {mask_path}")
                if image_info(mask_path)[:2] != image_info(path)[:2]:
                    raise BatchError("Mask dimensions do not match the source; the runner never resizes masks.")
                mask_hash = file_hash(mask_path)
        except (BatchError, OSError, UnicodeError) as exc:
            preflight_error = str(exc)
        prompt = "\n".join(part.strip() for part in (args.prompt_prefix, body, args.prompt_suffix) if part.strip())
        if generation and not prompt:
            preflight_error = preflight_error or "The resolved edit prompt is empty."
        for variant in range(1, args.variants + 1):
            job_id = digest([fingerprint, relative, source_hash, mask_hash, prompt, variant])
            grain_seed = (int(digest(["grain-v1", postprocess["grain_seed"], job_id])[:16], 16) & MAX_SEED
                          if postprocess is not None and postprocess["grain"] > 0 else None)
            jobs.append({"job_id": job_id, "path": path, "source": relative,
                         "source_sha256": source_hash, "mask_path": mask_path,
                         "mask_sha256": mask_hash, "prompt": prompt, "variant": variant,
                         "seed": seed_for(args.seed_mode, args.seed, relative, variant) if generation else None,
                         "grain_seed": grain_seed,
                         "preflight_error": preflight_error})
    return config, fingerprint, jobs, references


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect refused; use the final ComfyUI URL", headers, fp)


class ComfyClient:
    def __init__(self, server, request_timeout=30, auth_env=None, auth_header="Authorization"):
        self.server = server.rstrip("/")
        self.timeout = request_timeout
        self.headers = {}
        self.secret = os.environ.get(auth_env, "") if auth_env else ""
        if auth_env and not self.secret:
            raise BatchError(f"Authentication environment variable {auth_env} is empty or missing.")
        if "\r" in self.secret or "\n" in self.secret:
            raise BatchError("Authentication header value contains a newline.")
        if self.secret:
            self.headers[auth_header] = self.secret
        self.opener = urllib.request.build_opener(NoRedirect())

    def redact(self, text):
        return str(text).replace(self.secret, "[REDACTED]") if self.secret else str(text)

    def request(self, method, endpoint, payload=None, content_type="application/json"):
        headers = {**self.headers, "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = content_type
            if not isinstance(payload, bytes):
                payload = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.server + endpoint, data=payload, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read(16 * 1024 * 1024 + 1)
            if len(body) > 16 * 1024 * 1024:
                raise TransportError("Server JSON response exceeds 16 MiB.")
            return json.loads(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise ServerError(self.redact(f"HTTP {exc.code} from {endpoint}: {detail[:2000]}")) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise TransportError(self.redact(f"Connection error during {method} {endpoint}: {exc}")) from exc
        except ValueError as exc:
            raise TransportError(f"Server returned invalid JSON for {method} {endpoint}.") from exc

    def get(self, endpoint):
        for attempt in range(3):
            try:
                return self.request("GET", endpoint)
            except TransportError:
                if attempt == 2:
                    raise
                time.sleep(0.25 * (2 ** attempt))

    def upload(self, path, subfolder, name):
        boundary = "qwenbatch" + uuid.uuid4().hex
        parts = []
        for key, value in (("type", "input"), ("subfolder", subfolder), ("overwrite", "false")):
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8"))
        parts.extend((path.read_bytes(), f"\r\n--{boundary}--\r\n".encode()))
        result = self.request("POST", "/upload/image", b"".join(parts), "multipart/form-data; boundary=" + boundary)
        if not isinstance(result, dict) or not isinstance(result.get("name"), str) or result.get("type", "input") != "input":
            raise BatchError("Upload response did not identify an input image.")
        name = result["name"]
        folder = result.get("subfolder", "")
        if not name or any(p == ".." for p in (folder + "/" + name).replace("\\", "/").split("/")):
            raise BatchError("Upload response contains an invalid image path.")
        return (folder.strip("/") + "/" + name).lstrip("/") + " [input]"

    def submit(self, graph, client_id, run_id, job_id):
        response = self.request("POST", "/prompt", {"prompt": graph, "client_id": client_id,
                                 "extra_data": {"qwen_batch": {"run_id": run_id, "job_id": job_id}}})
        if not isinstance(response, dict) or response.get("node_errors") or not response.get("prompt_id"):
            raise BatchError(self.redact("ComfyUI rejected the prompt: " + canonical_json(response)[:3000]))
        return str(response["prompt_id"])

    def get_history(self, prompt_id):
        response = self.get("/history/" + urllib.parse.quote(prompt_id, safe=""))
        if not isinstance(response, dict):
            raise TransportError("History response must be a JSON object.")
        return response.get(prompt_id)

    def recover_submission(self, run_id, job_id):
        """Find our own tagged submission after a lost POST response; never mutate the queue."""
        matches = set()

        def inspect(row):
            if isinstance(row, list) and len(row) > 3 and isinstance(row[3], dict):
                tag = row[3].get("qwen_batch", {})
                if tag == {"run_id": run_id, "job_id": job_id}:
                    matches.add(str(row[1]))

        queue = self.get("/queue")
        if not isinstance(queue, dict):
            raise PendingJob("Cannot recover the submission: queue response is not a JSON object.")
        for kind in ("queue_running", "queue_pending"):
            rows = queue.get(kind, [])
            if not isinstance(rows, list):
                raise PendingJob("Cannot recover the submission: queue entries are malformed.")
            for row in rows:
                inspect(row)
        history = self.get("/history?max_items=500")
        if not isinstance(history, dict):
            raise PendingJob("Cannot recover the submission: history response is not a JSON object.")
        for record in history.values():
            if isinstance(record, dict):
                inspect(record.get("prompt"))
        if len(matches) == 1:
            return matches.pop()
        raise PendingJob("Submission outcome is unresolved. Check this run's tagged job in ComfyUI; "
                         "the runner will not risk submitting a duplicate. Recent history was searched.")


def history_result(history, expected_saves):
    if not isinstance(history, dict):
        return None
    status = history.get("status") or {}
    messages = status.get("messages") or []
    failed_events = [m for m in messages if isinstance(m, list) and m and m[0] in {"execution_error", "execution_interrupted"}]
    if status.get("status_str") == "error" or failed_events:
        return "failed", [], "ComfyUI execution failed: " + canonical_json(failed_events or status)[:3000]
    if status.get("completed") is not True or status.get("status_str") != "success":
        return None
    outputs = history.get("outputs") or {}
    images = []
    missing = []
    for node_id in expected_saves:
        node_images = (outputs.get(node_id) or {}).get("images") or []
        valid = [image for image in node_images if isinstance(image, dict) and image.get("filename")]
        if not valid:
            missing.append(node_id)
        images.extend({"node_id": node_id, **image} for image in valid)
    if missing:
        return "completed_no_output", images, "Server completed successfully but expected save outputs are missing: " + ", ".join(missing)
    return "completed", images, None


def output_prefix(manifest, config, job):
    relative = Path(job["source"])
    parents = [safe_component(part) for part in relative.parent.parts if part != "."]
    stem = safe_component(relative.stem)
    # A path hash disambiguates same stems/extensions, case, and sanitized names.
    identity = (job["job_id"][:10] if config["mapping"]["version"] >= 2
                else digest([job["source"], job["source_sha256"], job["mask_sha256"], job["prompt"]])[:10])
    filename = f"{stem}__{identity}__v{job['variant']:03d}"
    return "/".join([config["output_subfolder"], manifest["run_id"], *parents, filename])


def run_jobs(args, template, mapping, config, fingerprint, jobs, references, manifest_path):
    generation = mapping.get("task", "generate") == "generate"
    manifest = read_json(manifest_path) if manifest_path.exists() else None
    if manifest is not None:
        if not args.resume:
            raise BatchError("State already exists. Use --resume or choose a new --state-dir.")
        if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("config_fingerprint") != fingerprint:
            raise BatchError("Resume configuration differs from this manifest. Use a new --state-dir for changed settings.")
        if args.run_id and args.run_id != manifest.get("run_id"):
            raise BatchError("--run-id differs from the existing run.")
    else:
        if args.resume:
            raise BatchError("--resume was requested, but this state directory has no manifest.")
        manifest = {"schema_version": SCHEMA_VERSION, "run_id": args.run_id or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8],
                    "client_id": str(uuid.uuid4()), "created_at": utc_now(), "config_fingerprint": fingerprint,
                    "configuration": config, "jobs": {}, "uploads": {}}
    for planned in jobs:
        if planned["job_id"] not in manifest["jobs"]:
            record = {k: planned[k] for k in ("job_id", "source", "source_sha256", "mask_sha256", "prompt", "variant")}
            record.update(seed=(planned["seed"] if planned["seed"] is not None else secrets.randbits(63)) if generation else None,
                          status="pending", attempts=[], outputs=[])
            if config.get("postprocess") is not None:
                record["grain_seed"] = planned["grain_seed"]
            manifest["jobs"][planned["job_id"]] = record

    def persist():
        manifest["updated_at"] = utc_now()
        atomic_json(manifest_path, manifest)

    persist()
    client = ComfyClient(args.server, args.request_timeout, args.auth_env, args.auth_header)
    saves = [mapping["save"], *mapping["additional_saves"]]
    expected_saves = [save["node_id"] for save in saves]
    active_record = None
    failures = 0

    def upload(path, sha256, role):
        if file_hash(path) != sha256:
            raise BatchError(f"Input changed after planning: {path.name}. Run again to hash the current file.")
        key = digest([role, sha256, path.name])
        if not args.reupload and key in manifest["uploads"]:
            return manifest["uploads"][key]["reference"]
        name = sha256[:16] + "__" + safe_component(path.name)
        remote = client.upload(path, f"qwen_batch/{manifest['run_id']}/{role}", name)
        manifest["uploads"][key] = {"sha256": sha256, "name": path.name, "reference": remote, "uploaded_at": utc_now()}
        persist()
        return remote

    def finish(record, state, outputs, error):
        record.update(status=state, outputs=outputs, error=client.redact(error) if error else None, finished_at=utc_now())
        if record["attempts"]:
            record["attempts"][-1].update(status=state, finished_at=record["finished_at"], error=record["error"])
        persist()

    try:
        # A previous interrupted run may have an accepted job outside today's
        # range/content selection. Resolve it before submitting any new work.
        selected_ids = {job["job_id"] for job in jobs}
        outstanding = [r for r in manifest["jobs"].values() if r["status"] in UNFINISHED_STATES and r["job_id"] not in selected_ids]
        queue = [(None, r) for r in outstanding] + [(p, manifest["jobs"][p["job_id"]]) for p in jobs]
        for index, (planned, record) in enumerate(queue, start=1):
            active_record = record
            label = f"[{index}/{len(queue)}] {record['source']} variant {record['variant']}"
            if record["status"] == "completed":
                print(label + " — skipped: completed with matching input/settings", flush=True)
                continue
            if record["status"] in FAILED_STATES and not args.retry_failed:
                failures += 1
                print(label + " — skipped: previous failure (use --retry-failed)", flush=True)
                if args.on_error == "stop":
                    break
                continue
            if planned and planned["preflight_error"]:
                finish(record, "invalid", [], planned["preflight_error"])
                failures += 1
                print(label + " — invalid: " + record["error"], flush=True)
                if args.on_error == "stop":
                    break
                continue
            try:
                if record["status"] in {"submitting", "submission_unknown"}:
                    try:
                        recovered = client.recover_submission(manifest["run_id"], record["job_id"])
                    except BatchError as exc:
                        record["last_poll_error"] = client.redact(str(exc))
                        persist()
                        raise PendingJob("Submission recovery stopped while a job may already be queued. Resume to retry recovery.") from exc
                    record["prompt_id"] = recovered
                    record["status"] = "queued"
                    persist()
                if record["status"] not in {"queued", "running"}:
                    graph = copy.deepcopy(template)
                    source_ref = upload(planned["path"], planned["source_sha256"], "sources")
                    put_value(graph, mapping["source"], source_ref)
                    if args.mask_mode == "separate":
                        mask_ref = upload(planned["mask_path"], planned["mask_sha256"], "masks")
                        put_value(graph, mapping["mask"], mask_ref)
                    for ref_index, reference in enumerate(references):
                        ref = upload(reference["path"], reference["sha256"], "references")
                        put_value(graph, mapping["references"][ref_index], ref)
                    if generation:
                        put_value(graph, mapping["prompt"], record["prompt"])
                        put_value(graph, mapping["seed"], record["seed"])
                    inject_postprocess(graph, mapping, config.get("postprocess"), record.get("grain_seed"))
                    prefix = output_prefix(manifest, config, record)
                    put_value(graph, mapping["save"], prefix)
                    for save in mapping["additional_saves"]:
                        put_value(graph, save, prefix + "__" + save["suffix"])
                    record.update(status="submitting", error=None, output_prefix=prefix, started_at=utc_now())
                    record["attempts"].append({"attempt": len(record["attempts"]) + 1, "started_at": record["started_at"], "status": "submitting"})
                    persist()
                    try:
                        prompt_id = client.submit(graph, manifest["client_id"], manifest["run_id"], record["job_id"])
                    except TransportError as exc:
                        record.update(status="submission_unknown", error=str(exc))
                        persist()
                        raise PendingJob("Prompt submission response was lost. Resume to search for this tagged job; no duplicate was queued.") from exc
                    record.update(status="queued", prompt_id=prompt_id)
                    record["attempts"][-1].update(status="queued", prompt_id=prompt_id)
                    persist()
                    seed_description = f", generation seed {record['seed']}" if generation else ""
                    if record.get("grain_seed") is not None:
                        seed_description += f", grain seed {record['grain_seed']}"
                    print(label + f" — queued {prompt_id}" + seed_description, flush=True)
                else:
                    print(label + f" — resuming history polling for {record['prompt_id']}", flush=True)
                deadline = time.monotonic() + args.poll_timeout
                while True:
                    try:
                        history = client.get_history(record["prompt_id"])
                    except BatchError as exc:
                        record["last_poll_error"] = client.redact(str(exc))
                        persist()
                        raise PendingJob("Polling stopped while a submitted job may still be running. Resume to continue polling.") from exc
                    terminal = history_result(history, expected_saves)
                    if terminal:
                        finish(record, *terminal)
                        break
                    if time.monotonic() >= deadline:
                        raise PendingJob("Polling timed out; the submitted job may still run. Resume this state directory.")
                    time.sleep(min(args.poll_interval, max(0, deadline - time.monotonic())))
                if record["status"] != "completed":
                    failures += 1
                    print(label + " — " + record["status"] + ": " + record["error"], flush=True)
                    if args.on_error == "stop":
                        break
                else:
                    print(label + f" — completed; {len(record['outputs'])} saved image(s)", flush=True)
            except PendingJob:
                raise
            except (BatchError, OSError) as exc:
                finish(record, "failed", [], str(exc))
                failures += 1
                print(label + " — failed: " + record["error"], flush=True)
                if args.on_error == "stop":
                    break
    except KeyboardInterrupt:
        if active_record and active_record["status"] == "submitting":
            active_record["status"] = "submission_unknown"
        persist()
        print("Interrupted. Completed work is saved in the manifest. Submitted jobs may continue; no server jobs were cancelled.", file=sys.stderr)
        return 130
    except PendingJob as exc:
        persist()
        print(client.redact(str(exc)) + " No further jobs were submitted and no jobs were cancelled.", file=sys.stderr)
        return 3
    selected = [manifest["jobs"][job["job_id"]] for job in jobs]
    complete = sum(record["status"] == "completed" for record in selected)
    print(f"Run {manifest['run_id']}: {complete}/{len(selected)} selected jobs completed. Manifest: {manifest_path}", flush=True)
    return 1 if failures or complete != len(selected) else 0


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--template", required=True, help="ComfyUI API-format template JSON")
    p.add_argument("--mapping", required=True, help="version 1 generation or version 2 generation/upscaling mapping JSON")
    p.add_argument("--input-dir", required=True, help="Folder of source still images")
    p.add_argument("--state-dir", required=True, help="Durable local manifest folder; use a separate folder per settings run")
    p.add_argument("--server", default="http://127.0.0.1:8188")
    p.add_argument("--auth-env", help="Environment variable containing the complete auth header value; never written to manifest")
    p.add_argument("--auth-header", default="Authorization")
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--exclude", action="append", default=[], help="Relative-path glob to exclude; repeatable")
    p.add_argument("--start", type=int, default=0, help="Zero-based source offset after natural sorting")
    p.add_argument("--limit", type=int, help="Maximum source images, before variants")
    p.add_argument("--variants", type=int, default=1)
    p.add_argument("--seed-mode", choices=("fixed", "stable-per-source", "random-recorded"),
                   help="Generation seed strategy; default is stable-per-source")
    p.add_argument("--seed", type=int, help="Base generation seed (default 42); fixed mode adds variant - 1")
    p.add_argument("--prompt", help="Shared instruction; defaults to mapped template text")
    p.add_argument("--prompt-file", help="UTF-8 shared instruction file")
    p.add_argument("--sidecar-prompts", action="store_true", help="Use matching .txt instructions when present, otherwise shared instruction")
    p.add_argument("--sidecar-dir", help="Optional alternate prompt root, matching relative source paths")
    p.add_argument("--require-sidecars", action="store_true")
    p.add_argument("--prompt-prefix", default="")
    p.add_argument("--prompt-suffix", default="")
    p.add_argument("--reference", action="append", default=[], help="Upload a shared reference into the next mapping.references slot; repeatable")
    p.add_argument("--mask-mode", choices=("none", "separate", "alpha"), default="none",
                   help="Alpha requires a PNG and a template wired to the source alpha mask; this flag does not rewire the graph")
    p.add_argument("--mask-dir", help="Root of same-size white-edit PNG masks, preserving relative folder structure")
    p.add_argument("--mask-suffix", default="", help="Mask suffix before .png, for example _mask")
    p.add_argument("--upscale", choices=("off", "lanczos", "ai"), help="Postprocess mode; defaults to the mapping (off for generation, lanczos for pure upscaling)")
    p.add_argument("--scale", type=float, help="Final size multiplier relative to the processing input, from 1 to 8")
    p.add_argument("--upscale-model", help="Installed ComfyUI upscale model filename; required for AI mode unless defined by the mapping")
    p.add_argument("--grain", type=float, help="Fine chromatic grain strength from 0 to 1; 0 disables grain")
    p.add_argument("--grain-seed", type=int, help="Base used to derive a deterministic grain seed per job; default comes from the mapping")
    p.add_argument("--output-subfolder", default="Qwen21/batch", help="Relative folder within the ComfyUI server output directory")
    p.add_argument("--run-id", help="Optional alphanumeric run name; default is UTC timestamp plus random suffix")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--retry-failed", action="store_true", help="Retry terminal failures with their previously recorded seeds")
    p.add_argument("--reupload", action="store_true", help="Refresh uploads if remote input files were removed")
    p.add_argument("--on-error", choices=("stop", "continue"), default="stop")
    p.add_argument("--request-timeout", type=float, default=30)
    p.add_argument("--poll-timeout", type=float, default=3600)
    p.add_argument("--poll-interval", type=float, default=1)
    p.add_argument("--dry-run", action="store_true", help="Offline validation/enumeration; no network, no manifest writes")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        args.generation_seed_options_explicit = args.seed is not None or args.seed_mode is not None
        if args.seed is None:
            args.seed = 42
        if args.seed_mode is None:
            args.seed_mode = "stable-per-source"
        if args.start < 0 or (args.limit is not None and args.limit < 1) or args.variants < 1:
            raise BatchError("--start must be nonnegative; --limit and --variants must be positive.")
        if not 0 <= args.seed <= MAX_SEED or min(args.request_timeout, args.poll_timeout, args.poll_interval) <= 0:
            raise BatchError("Seed must fit a nonnegative signed 64-bit integer; timeouts/interval must be positive.")
        if args.run_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.run_id):
            raise BatchError("--run-id must contain 1–80 letters, digits, underscores or hyphens.")
        if not re.fullmatch(r"[A-Za-z0-9-]+", args.auth_header):
            raise BatchError("Invalid authentication header name.")
        url = urllib.parse.urlsplit(args.server)
        if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise BatchError("--server must be an HTTP(S) URL without embedded credentials, query or fragment.")
        args.server = args.server.rstrip("/")
        args.output_subfolder = safe_subfolder(args.output_subfolder)
        if "/" in args.mask_suffix or "\\" in args.mask_suffix:
            raise BatchError("--mask-suffix cannot contain path separators.")
        template, mapping = validate_template(read_json(args.template), read_json(args.mapping))
        config, fingerprint, jobs, references = build_plan(args, template, mapping)
        state_dir = Path(args.state_dir).expanduser().resolve()
        manifest_path = state_dir / "manifest.json"
        if args.dry_run:
            manifest = read_json(manifest_path) if args.resume and manifest_path.exists() else None
            if manifest and manifest.get("config_fingerprint") != fingerprint:
                raise BatchError("Resume configuration differs from this manifest.")
            print(f"DRY RUN: {len(jobs)} jobs; fingerprint {fingerprint}; no network or state writes")
            for job in jobs:
                previous = (manifest or {}).get("jobs", {}).get(job["job_id"], {})
                print(json.dumps({"source": job["source"], "variant": job["variant"],
                                  "seed": previous.get("seed", job["seed"]),
                                  "grain_seed": previous.get("grain_seed", job["grain_seed"]),
                                  "postprocess": config.get("postprocess"),
                                  "prompt_characters": len(job["prompt"]),
                                  "mask": str(job["mask_path"]) if job["mask_path"] else args.mask_mode,
                                  "previous_status": previous.get("status"),
                                  "error": job["preflight_error"]}, ensure_ascii=False))
            return 2 if any(job["preflight_error"] for job in jobs) else 0
        with state_lock(state_dir):
            return run_jobs(args, template, mapping, config, fingerprint, jobs, references, manifest_path)
    except KeyboardInterrupt:
        print("Interrupted before submitting new work. No server jobs were cancelled.", file=sys.stderr)
        return 130
    except (BatchError, OSError, UnicodeError) as exc:
        # Defensive redaction even for errors outside the HTTP client.
        message = str(exc)
        secret = os.environ.get(args.auth_env, "") if args.auth_env else ""
        if secret:
            message = message.replace(secret, "[REDACTED]")
        print("Error: " + message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
