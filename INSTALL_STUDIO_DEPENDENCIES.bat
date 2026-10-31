@echo off
rem SPDX-License-Identifier: GPL-3.0-only
setlocal DisableDelayedExpansion
title Luminaire Edit Studio - Portable dependency installer
set "QWEN_STUDIO_INSTALLER=%~f0"
if exist "%~dp0main.py" if exist "%~dp0..\python_embeded\python.exe" goto :inner
if exist "%~dp0ComfyUI\main.py" if exist "%~dp0python_embeded\python.exe" goto :outer
echo ERROR: Put this BAT in the portable installation's ComfyUI folder,
echo or in the portable root beside the ComfyUI and python_embeded folders.
echo No portable Python was found. No dependencies were installed.
set "QWEN_STUDIO_RESULT=1"
goto :finished
:inner
set "QWEN_STUDIO_COMFY=%~dp0"
set "QWEN_STUDIO_PYTHON=%~dp0..\python_embeded\python.exe"
goto :launch
:outer
set "QWEN_STUDIO_COMFY=%~dp0ComfyUI"
set "QWEN_STUDIO_PYTHON=%~dp0python_embeded\python.exe"
:launch
"%QWEN_STUDIO_PYTHON%" -s -c "import os,pathlib; p=pathlib.Path(os.environ['QWEN_STUDIO_INSTALLER']); s=p.read_text(encoding='utf-8-sig'); body=s.partition(chr(10)+'# QWEN_STUDIO_PYTHON'+chr(10))[2]; assert body, 'Missing installer payload'; exec(compile(body,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})" %*
set "QWEN_STUDIO_RESULT=%errorlevel%"
:finished
echo.
if "%QWEN_STUDIO_RESULT%"=="0" echo Installer finished successfully.
if "%QWEN_STUDIO_RESULT%"=="1" echo Installation needs attention. Read the error above and the log, if created.
if "%QWEN_STUDIO_RESULT%"=="2" echo Dependencies installed; follow the compatibility notes above before use.
if not defined QWEN_STUDIO_NO_PAUSE pause
exit /b %QWEN_STUDIO_RESULT%
# QWEN_STUDIO_PYTHON
"""Single-file Windows Portable dependency installer for Luminaire Edit Studio.

The BAT launcher executes this section with the installation's embedded Python.
Installer version 1.1.0. No system Python, model downloads, or core updates.
"""
import argparse
from datetime import datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
import urllib.request
import zipfile


PACKS = (
    ("ausboss/ComfyUI-AusBoss", False),
    ("rgthree/rgthree-comfy", True),
    ("cubiq/ComfyUI_essentials", True),
    ("Adudeguyman/ComfyUI-Fantastic-MiniMaxH3-PromptBuilder", True),
    ("Mozer/ComfyUI-PixelDriftFix", True),
    ("Fannovel16/comfyui_controlnet_aux", True),
    ("kijai/ComfyUI-KJNodes", False),
)
PROTECTED = {
    "torch", "torchvision", "torchaudio", "xformers", "triton",
    "triton-windows", "numpy", "pillow", "av",
}
CORE_NODES = (
    "TextEncodeQwenImage21", "QwenImage21Cache", "CustomCombo",
    "ComfyMathExpression", "ImageAddNoise", "ImageUpscaleWithModel",
)
LOG = None


def say(message=""):
    print(message, flush=True)
    if LOG is not None:
        LOG.write(str(message) + "\n")
        LOG.flush()


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def installed_packages():
    result = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            result[normalized(name)] = dist.version
    return result


def protected_versions(packages):
    return {name: version for name, version in sorted(packages.items())
            if name in PROTECTED or name.startswith("nvidia-")}


def command_environment():
    env = os.environ.copy()
    # Ignore pip destination/index overrides and pip.ini, while retaining
    # standard HTTPS proxy and certificate environment settings.
    for key in list(env):
        if key.upper().startswith("PIP_"):
            del env[key]
    env["PIP_CONFIG_FILE"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run(command, cwd):
    say("\n> " + subprocess.list2cmdline([str(part) for part in command]))
    with subprocess.Popen(
        [str(part) for part in command], cwd=str(cwd),
        env=command_environment(), shell=False,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    ) as process:
        for line in process.stdout:
            say(line.rstrip("\r\n"))
        return process.wait()


def find_existing(custom_nodes, name):
    aliases = {normalized(name), normalized(name + "-main"),
               normalized(name + "-master")}
    matches = [path for path in custom_nodes.iterdir()
               if path.is_dir() and normalized(path.name) in aliases]
    if len(matches) > 1:
        raise RuntimeError("Multiple copies of " + name + ": "
                           + ", ".join(str(path) for path in matches)
                           + ". Keep one enabled copy, then rerun.")
    if matches:
        if not (matches[0] / "__init__.py").is_file():
            raise RuntimeError("Existing folder is incomplete: " + str(matches[0])
                               + ". It was left unchanged.")
        return matches[0]
    return None


def extract_repository(archive, destination):
    with zipfile.ZipFile(archive) as bundle:
        roots = set()
        for entry in bundle.infolist():
            path = PurePosixPath(entry.filename)
            if (not path.parts or path.is_absolute() or ".." in path.parts
                    or "\\" in entry.filename or ":" in entry.filename
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise RuntimeError("Unsafe path in repository ZIP: " + entry.filename)
            roots.add(path.parts[0])
        if len(roots) != 1:
            raise RuntimeError("Repository ZIP must contain one root folder.")
        bundle.extractall(destination)
    root = destination / next(iter(roots))
    if not (root / "__init__.py").is_file():
        raise RuntimeError("Downloaded node pack has no root __init__.py.")
    return root


def install_pack(repository, custom_nodes, work_dir, git):
    name = repository.split("/")[-1]
    existing = find_existing(custom_nodes, name)
    if existing is not None:
        say("REUSE: " + str(existing) + " (not updated)")
        return existing
    target = custom_nodes / name
    with tempfile.TemporaryDirectory(prefix="node-", dir=work_dir) as temporary:
        staging = Path(temporary)
        if git:
            root = staging / "repository"
            code = run([git, "clone", "--depth", "1",
                        "https://github.com/" + repository + ".git", root], custom_nodes)
            if code:
                raise RuntimeError("Git clone failed for " + name + ". Check the log and rerun.")
            if not (root / "__init__.py").is_file():
                raise RuntimeError("Downloaded node pack has no root __init__.py: " + name)
        else:
            say("DOWNLOAD ZIP: " + repository)
            archive = staging / "repository.zip"
            # HEAD follows the repository's default branch, including future renames.
            url = "https://codeload.github.com/" + repository + "/zip/HEAD"
            request = urllib.request.Request(url, headers={"User-Agent": "Luminaire-Edit-Studio-Installer/1.1"})
            with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
            root = extract_repository(archive, staging / "extracted")
        if target.exists():
            raise RuntimeError("Destination appeared during installation: " + str(target))
        root.rename(target)
    say("INSTALLED: " + str(target))
    return target


def core_gaps(comfy):
    pending = set(CORE_NODES)
    files = [comfy / "nodes.py"] + list((comfy / "comfy_extras").glob("*.py"))
    for path in files:
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            pending = {name for name in pending if name not in text}
    return sorted(pending)


def namespace_notes(packages):
    notes = []
    families = (
        ("OpenCV", ("opencv-python", "opencv-contrib-python",
                    "opencv-python-headless", "opencv-contrib-python-headless")),
        ("ONNX Runtime", ("onnxruntime", "onnxruntime-gpu", "onnxruntime-directml")),
    )
    for label, names in families:
        present = [name for name in names if name in packages]
        if len(present) > 1:
            notes.append(label + " has multiple distributions: " + ", ".join(present)
                         + ". They share an import namespace; check preprocessor imports. "
                         + "No installed variants were removed.")
    return notes


def main():
    global LOG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show paths and planned actions without downloads or changes.")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    comfy = Path(os.environ.get("QWEN_STUDIO_COMFY", "")).resolve()
    expected_python = comfy.parent / "python_embeded" / "python.exe"
    if not (comfy / "main.py").is_file() or not expected_python.is_file():
        raise RuntimeError("Cannot identify the ComfyUI Portable installation.")
    if Path(sys.executable).resolve() != expected_python.resolve():
        raise RuntimeError("This installer must run with the detected portable Python.")
    custom_nodes = comfy / "custom_nodes"
    git = shutil.which("git.exe") or shutil.which("git")
    before = installed_packages()
    protected = protected_versions(before)
    if args.dry_run:
        say("DRY RUN: no files, node packs, or packages will be changed.")
        say("ComfyUI: " + str(comfy))
        say("Python: " + str(expected_python))
        say("Download method: " + ("Git" if git else "GitHub ZIP; Git not required"))
        for repository, _ in PACKS:
            name = repository.split("/")[-1]
            existing = find_existing(custom_nodes, name) if custom_nodes.is_dir() else None
            say(("REUSE " + str(existing)) if existing else "INSTALL " + repository)
        say("Protected installed versions: " + json.dumps(protected, sort_keys=True))
        say("Requirements will be resolved together using this portable Python.")
        return 0
    if "torch" not in before:
        raise RuntimeError("Portable PyTorch is missing. Repair ComfyUI Portable first; "
                           "the installer will not choose a CPU/CUDA build for you.")
    if "pip" not in before:
        raise RuntimeError("pip is missing from portable Python. Repair the portable installation first.")
    work_dir = comfy / "user" / "qwen_studio_installer" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    work_dir.mkdir(parents=True, exist_ok=False)
    LOG = (work_dir / "install.log").open("w", encoding="utf-8")
    say("Luminaire Edit Studio - dependency installer 1.1.0")
    say("Close ComfyUI while installing. Internet access is required.")
    say("ComfyUI: " + str(comfy))
    say("Python: " + str(sys.executable))
    say("Log: " + str(work_dir / "install.log"))
    say("Download method: " + ("Git" if git else "GitHub ZIP; Git not required"))
    say("Existing node packs are reused. Update old copies through ComfyUI Manager.")
    (work_dir / "packages-before.json").write_text(json.dumps(before, indent=2, sort_keys=True), encoding="utf-8")
    constraints = work_dir / "protected-versions.txt"
    constraints.write_text("".join(name + "==" + version + "\n"
                                  for name, version in protected.items()), encoding="utf-8")
    say("Protected installed versions: " + json.dumps(protected, sort_keys=True))
    custom_nodes.mkdir(parents=True, exist_ok=True)
    requirements = []
    failures = []
    for repository, expects_requirements in PACKS:
        try:
            folder = install_pack(repository, custom_nodes, work_dir, git)
            requirement = folder / "requirements.txt"
            if expects_requirements and not requirement.is_file():
                raise RuntimeError("Required manifest is missing: " + str(requirement))
            if requirement.is_file():
                content = requirement.read_text(encoding="utf-8-sig")
                if any(line.strip() and not line.lstrip().startswith("#") for line in content.splitlines()):
                    requirements.append(requirement)
        except Exception as error:
            failures.append(str(error))
            say("ERROR: " + str(error))
    if failures:
        say("\nNode pack setup is incomplete. Python packages were not changed. Fix the errors and rerun.")
        return 1
    pip_command = [sys.executable, "-s", "-m", "pip", "--isolated"]
    if requirements:
        command = pip_command + ["install", "--disable-pip-version-check", "--no-input",
                                 "--prefer-binary", "--upgrade-strategy", "only-if-needed",
                                 "--constraint", constraints]
        for requirement in requirements:
            command.extend(["-r", requirement])
        code = run(command, comfy)
    else:
        code = 0
    after = installed_packages()
    (work_dir / "packages-after.json").write_text(json.dumps(after, indent=2, sort_keys=True), encoding="utf-8")
    changed = [name for name, version in protected.items() if after.get(name) != version]
    if changed:
        raise RuntimeError("Protected package versions changed unexpectedly: " + ", ".join(changed)
                           + ". Compare the package snapshots in the log folder.")
    if code:
        say("\nDependency installation failed. The log contains pip's exact conflict or download error.")
        say("Protected versions were kept. Resolve the reported conflict or update/repair the portable")
        say("installation using its official updater, then rerun. Constraints were not removed.")
        return 1
    notes = namespace_notes(after)
    if run(pip_command + ["check", "--disable-pip-version-check"], comfy):
        notes.append("pip check reported package conflicts (possibly pre-existing). Review the log before use.")
    missing = core_gaps(comfy)
    if missing:
        notes.append("ComfyUI source preflight could not find: " + ", ".join(missing)
                     + ". Close ComfyUI, run the portable root's update\\update_comfyui.bat, "
                     + "then rerun this installer. This script does not update core or its frontend.")
    for name in ("diffusion_models", "text_encoders", "vae", "loras", "model_patches", "upscale_models"):
        (comfy / "models" / name).mkdir(parents=True, exist_ok=True)
    say(f"\nAll {len(PACKS)} node packs are present and their Python requirements were installed.")
    say("Model weights are separate. See DEPENDENCIES.md; AI upscalers go in models\\upscale_models.")
    say("Restart ComfyUI and refresh its browser tab. Check startup for any node import errors.")
    say("Source checks do not replace a live ComfyUI startup or GPU test.")
    for note in notes:
        say("NOTE: " + note)
    say("Log and package snapshots: " + str(work_dir))
    return 2 if notes else 0


if __name__ == "__main__":
    try:
        result = main()
    except SystemExit as error:
        result = 0 if error.code == 0 else 1
    except KeyboardInterrupt:
        say("\nCancelled. Completed downloads/installs are retained; rerun to continue.")
        result = 1
    except Exception as error:
        say("\nERROR: " + str(error))
        if LOG is not None:
            LOG.write(traceback.format_exc())
            say("Details: " + LOG.name)
        result = 1
    finally:
        if LOG is not None:
            LOG.close()
    sys.exit(result)
