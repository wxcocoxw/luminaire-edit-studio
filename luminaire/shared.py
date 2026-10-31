# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import re
import logging
import threading
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageFilter

CATEGORY = "Luminaire Edit Studio"
PRESETS = {"Keep input size": None, "Scale input": None, "Custom": None,
           "HD landscape": (1920, 1080), "UHD landscape": (3840, 2160),
           "Square 1080": (1080, 1080), "Portrait 4:5": (1080, 1350),
           "Vertical 9:16": (1080, 1920)}
ATTENTION_BACKENDS = ['Auto', 'PyTorch', 'Comfy Kitchen INT8', 'SageAttention']


def model_file_identity(kind, name):
    import folder_paths
    path = Path(folder_paths.get_full_path_or_raise(kind, name)).resolve()
    stat = path.stat()
    return str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def unload_owned_model(model):
    """Release this model family only; leave CLIP, VAE and other caches alone."""
    import comfy.model_management as memory
    memory.unload_model_and_clones(model, unload_additional_models=False)


class UpscalerCache:
    """One shared descriptor, bounded across all delivery nodes and folder items.

    ComfyUI retains control of GPU residency through the native model patcher.
    Replacing the file or selecting a different model invalidates this entry.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._identity = None
        self._model = None

    def get(self, name):
        from comfy_extras.nodes_upscale_model import UpscaleModelLoader
        identity = model_file_identity('upscale_models', name)
        with self._lock:
            if identity == self._identity:
                logging.info('[Luminaire Edit Studio] AI upscaler cache hit: %s', name)
                return self._model
            # Evict before loading so switching models does not keep both resident.
            if self._model is not None:
                unload_owned_model(self._model.patcher)
            self._model = None
            self._identity = None
            model = UpscaleModelLoader.execute(name)[0]
            self._model, self._identity = model, identity
            logging.info('[Luminaire Edit Studio] AI upscaler cache miss: %s', name)
            return model


UPSCALER_CACHE = UpscalerCache()


def with_attention(model, backend):
    if backend == 'Auto':
        return model
    if backend not in ATTENTION_BACKENDS:
        raise ValueError(f'Unknown attention backend: {backend}')
    import comfy.ldm.modules.attention as attention
    import comfy.model_management as memory
    if backend == 'Comfy Kitchen INT8':
        import comfy_kitchen
        if not comfy_kitchen.int8_attention_is_available(memory.get_torch_device()):
            raise ValueError('Comfy Kitchen INT8 attention is unavailable on this installation/device. Select Auto or PyTorch.')
    key = {'Comfy Kitchen INT8':'comfy_kitchen_int8', 'PyTorch':'pytorch', 'SageAttention':'sage'}[backend]
    function = attention.get_attention_function(key, None)
    if function is None:
        raise ValueError(f'{backend} attention is unavailable. Select Auto or PyTorch.')
    patched = model.clone()
    patched.set_model_optimized_attention(function)
    logging.info('[Luminaire Edit Studio] Requested sampling attention: %s', key)
    return patched


def image_tensor(image):
    if image.ndim != 4 or image.shape[-1] not in (3, 4) or image.shape[0] < 1:
        raise ValueError("Expected a nonempty RGB or RGBA IMAGE batch.")
    return image


def resize(image, width, height, method="Bicubic"):
    if (image.shape[2], image.shape[1]) == (width, height):
        return image
    if method == "Lanczos":
        batches = []
        for frame in image.detach().float().cpu():
            channels = [np.asarray(Image.fromarray(frame[..., c].numpy()).resize((width, height), Image.Resampling.LANCZOS)).copy()
                        for c in range(frame.shape[-1])]
            batches.append(torch.from_numpy(np.stack(channels, axis=-1)))
        return torch.stack(batches).to(image).clamp(0, 1)
    # Float interpolation avoids an unnecessary 8-bit conversion before compositing.
    return F.interpolate(image.movedim(-1, 1), size=(height, width), mode="bicubic",
                         align_corners=False, antialias=True).movedim(1, -1).clamp(0, 1)


def resize_rgba(image, width, height, method="Bicubic"):
    if image.shape[-1] != 4:
        return resize(image, width, height, method)
    if (image.shape[2], image.shape[1]) == (width, height):
        return image
    # Resample premultiplied colors to avoid dark/colored fringes at transparent edges.
    a = image[..., 3:4]
    p = resize(torch.cat((image[..., :3] * a, a), dim=-1), width, height, method)
    alpha = p[..., 3:4]
    rgb = torch.where(alpha > 1e-7, p[..., :3] / alpha.clamp_min(1e-7), 0).clamp(0, 1)
    return torch.cat((rgb, alpha), dim=-1)


def match_batch(tensor, count):
    if tensor.shape[0] == count:
        return tensor
    if tensor.shape[0] == 1:
        return tensor.expand(count, *tensor.shape[1:])
    raise ValueError("Batch sizes must match, or the source/mask must contain one item.")


def protection_mask(mask, source, grow, feather):
    h, w = source.shape[1:3]
    if mask.ndim == 2:
        mask = mask.unsqueeze(0)
    if mask.ndim != 3:
        raise ValueError("Protection requires a MASK tensor with shape B,H,W.")
    mask = match_batch(mask.to(source.device, source.dtype), source.shape[0]).clamp(0, 1)
    if tuple(mask.shape[-2:]) != (h, w):
        if torch.count_nonzero(mask):
            raise ValueError("The painted protection mask must have the source image dimensions.")
        mask = torch.zeros((source.shape[0], h, w), device=source.device, dtype=source.dtype)
    hard = mask >= 0.5
    radius = int(grow)
    if radius:
        hard = F.max_pool2d(hard.float().unsqueeze(1), 2 * radius + 1, 1, radius)[:, 0] > 0
    weight = torch.maximum(mask, hard.to(mask.dtype))
    if feather:
        blurred = []
        for m in weight:
            pil = Image.fromarray((m.detach().cpu().numpy() * 255).astype(np.uint8))
            blurred.append(torch.from_numpy(np.asarray(pil.filter(ImageFilter.GaussianBlur(feather))).copy()).float() / 255)
        weight = torch.maximum(weight, torch.stack(blurred).to(weight))
    # Never soften the protected core. Feathering extends outside it.
    return weight.unsqueeze(-1), hard


class QwenStudioProtection:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": ("IMAGE",), "mask": ("MASK",),
                "enabled": ("BOOLEAN", {"default": False}),
                "grow": ("INT", {"default": 0, "min": 0, "max": 128}),
                "feather": ("INT", {"default": 8, "min": 0, "max": 128})}}
    RETURN_TYPES = ("STUDIO_PROTECTION", "IMAGE", "MASK")
    RETURN_NAMES = ("protection", "protected_overlay", "protected_mask")
    FUNCTION = "prepare"
    CATEGORY = CATEGORY

    def prepare(self, source, mask, enabled, grow, feather):
        source = image_tensor(source)
        weight, _ = protection_mask(mask, source, grow, feather)
        overlay = source[..., :3].clone()
        color = overlay.new_tensor([1.0, 0.15, 0.2])
        overlay = overlay * (1 - weight * .45) + color * weight * .45
        return ({"source": source, "weight": weight, "enabled": bool(enabled)}, overlay, weight[..., 0])


class QwenStudioMaskPolicy:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"mask": ("MASK",), "polarity": (["White edits", "White protects"],)}}
    RETURN_TYPES = ("MASK", "MASK")
    RETURN_NAMES = ("edit_mask", "protect_mask")
    FUNCTION = "convert"
    CATEGORY = CATEGORY

    def convert(self, mask, polarity):
        mask = mask.clamp(0, 1)
        return (mask, 1 - mask) if polarity == 'White edits' else (1 - mask, mask)


class QwenStudioRestoreProtected:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "protection": ("STUDIO_PROTECTION",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "restore"
    CATEGORY = CATEGORY

    def restore(self, image, protection):
        image = image_tensor(image)
        if not protection["enabled"]:
            return (image,)
        source = match_batch(protection["source"].to(image), image.shape[0])
        weight = match_batch(protection["weight"].to(image), image.shape[0])
        generated = resize_rgba(image, source.shape[2], source.shape[1])
        # Preserve source alpha when the edited branch is RGB (e.g. alignment).
        if source.shape[-1] == 4 and generated.shape[-1] == 3:
            generated = torch.cat((generated, source[..., 3:4]), dim=-1)
        elif source.shape[-1] == 3 and generated.shape[-1] == 4:
            source = torch.cat((source, torch.ones_like(source[..., :1])), dim=-1)
        mixed = generated * (1 - weight) + source * weight
        return (torch.where(weight >= 1, source, mixed),)


class QwenStudioDeliveryPreset:
    @classmethod
    def INPUT_TYPES(cls):
        import folder_paths
        return {"required": {
            "preset": (list(PRESETS),),
            "width": ("INT", {"default": 1920, "min": 1, "max": 16384}),
            "height": ("INT", {"default": 1080, "min": 1, "max": 16384}),
            "scale": ("FLOAT", {"default": 2.0, "min": .125, "max": 8, "step": .125}),
            "fit": (["Pad", "Crop", "Stretch"],),
            "upscale": (["Lanczos", "Bicubic", "AI"],),
            "upscale_model": (["none"] + folder_paths.get_filename_list("upscale_models"),),
            "alpha": (["Preserve", "Flatten"],),
            "background": (["Black", "White", "Transparent"],),
            "grain": ("FLOAT", {"default": 0, "min": 0, "max": 1, "step": .005}),
            "grain_seed": ("INT", {"default": 42, "min": 0, "max": 0xffffffffffffffff}),
            "project": ("STRING", {"default": "Qwen21Studio"}),
            "version": ("STRING", {"default": "v001"})}}
    RETURN_TYPES = ("STUDIO_DELIVERY",)
    RETURN_NAMES = ("delivery",)
    FUNCTION = "configure"
    CATEGORY = CATEGORY

    def configure(self, **settings):
        if settings["upscale"] == "AI" and settings["upscale_model"] == "none":
            raise ValueError("Select an installed AI upscale model or choose Lanczos/Bicubic.")
        return (dict(settings),)


def delivery_geometry(width, height, settings):
    preset = settings["preset"]
    if preset == "Keep input size":
        return width, height
    if preset == "Scale input":
        return max(1, round(width * settings["scale"])), max(1, round(height * settings["scale"]))
    if preset == "Custom":
        return int(settings["width"]), int(settings["height"])
    return PRESETS[preset]


def layout(image, settings):
    image = image_tensor(image)
    tw, th = delivery_geometry(image.shape[2], image.shape[1], settings)
    if tw * th > 80_000_000:
        raise ValueError("Delivery exceeds 80 megapixels. Reduce the dimensions or scale.")
    method = 'Lanczos' if settings['upscale'] == 'AI' else settings['upscale']
    if (image.shape[2], image.shape[1]) == (tw, th):
        out = image
    elif settings["fit"] == "Stretch":
        out = resize_rgba(image, tw, th, method)
    else:
        factor = (max if settings["fit"] == "Crop" else min)(tw / image.shape[2], th / image.shape[1])
        rw, rh = max(1, round(image.shape[2] * factor)), max(1, round(image.shape[1] * factor))
        scaled = resize_rgba(image, rw, rh, method)
        if settings["fit"] == "Crop":
            x, y = (rw - tw) // 2, (rh - th) // 2
            out = scaled[:, y:y + th, x:x + tw]
        else:
            transparent = settings["background"] == "Transparent" and settings["alpha"] == "Preserve"
            if transparent and scaled.shape[-1] == 3:
                scaled = torch.cat((scaled, torch.ones_like(scaled[..., :1])), dim=-1)
            fill = 1.0 if settings["background"] == "White" else 0.0
            out = scaled.new_full((scaled.shape[0], th, tw, scaled.shape[-1]), fill)
            if out.shape[-1] == 4:
                out[..., 3] = 0 if transparent else 1
            x, y = (tw - rw) // 2, (th - rh) // 2
            out[:, y:y + rh, x:x + rw] = scaled
    if settings["alpha"] == "Flatten" and out.shape[-1] == 4:
        bg = 1 if settings["background"] == "White" else 0
        out = out[..., :3] * out[..., 3:4] + bg * (1 - out[..., 3:4])
    return out


class QwenStudioLayoutPreview:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "delivery": ("STUDIO_DELIVERY",)}}
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("layout_preview", "dimensions")
    FUNCTION = "preview"
    CATEGORY = CATEGORY

    def preview(self, image, delivery):
        w, h = delivery_geometry(image.shape[2], image.shape[1], delivery)
        # Layout preview is capped; it neither loads the AI model nor adds grain.
        factor = min(1, 768 / max(w, h))
        settings = dict(delivery, preset="Custom", width=max(1, round(w * factor)), height=max(1, round(h * factor)))
        return (layout(image, settings), f"{w} x {h} | {delivery['fit']} | {delivery['alpha']}")


class QwenStudioDeliver:
    @classmethod
    def IS_CHANGED(cls, delivery=None, **kwargs):
        if delivery is not None and delivery.get('upscale') == 'AI':
            return model_file_identity('upscale_models', delivery['upscale_model'])
        return None

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "delivery": ("STUDIO_DELIVERY",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "finish"
    CATEGORY = CATEGORY

    def finish(self, image, delivery):
        image = image_tensor(image)
        target = delivery_geometry(image.shape[2], image.shape[1], delivery)
        work = image
        if delivery["upscale"] == "AI":
            from comfy_extras.nodes_upscale_model import ImageUpscaleWithModel
            model = UPSCALER_CACHE.get(delivery["upscale_model"])
            work = ImageUpscaleWithModel.execute(model, image)[0]
        out = layout(work, dict(delivery, preset="Custom", width=target[0], height=target[1]))
        if delivery["grain"]:
            out = out.clone()
            generator = torch.Generator(device="cpu").manual_seed(delivery["grain_seed"])
            for i in range(out.shape[0]):
                noise = torch.randn(out[i, ..., :3].shape, generator=generator, device="cpu", dtype=torch.float32).to(out)
                out[i, ..., :3] = (out[i, ..., :3] + noise * delivery["grain"]).clamp(0, 1)
        return (out,)


def safe_component(value):
    value = re.sub(r'[^\w. -]', '_', str(value), flags=re.UNICODE).strip(' .')[:100]
    if not value or value in (".", ".."):
        return "untitled"
    if value.split('.')[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)]}:
        value = "_" + value
    return value


class QwenStudioSaveDelivery:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "delivery": ("STUDIO_DELIVERY",),
                             "filename_prefix": ("STRING", {"default": "edit/final/image"})},
                "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"}}
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = CATEGORY

    def save(self, images, delivery, filename_prefix, prompt=None, extra_pnginfo=None):
        import nodes
        # Keep task/source subfolders, strip a legacy project prefix, and prevent traversal.
        parts = str(filename_prefix).replace('\\', '/').split('/')
        if parts and parts[0] == 'Qwen21Studio':
            parts = parts[1:]
        parts = [safe_component(p) for p in parts if p]
        prefix = '/'.join([safe_component(delivery['project']), safe_component(delivery['version']), *parts])
        extra = dict(extra_pnginfo or {})
        extra['qwen_studio_delivery'] = delivery
        return nodes.SaveImage().save_images(images, prefix, prompt, extra)



NODE_CLASS_MAPPINGS = {node.__name__: node for node in (QwenStudioProtection, QwenStudioMaskPolicy, QwenStudioRestoreProtected, QwenStudioDeliveryPreset, QwenStudioLayoutPreview, QwenStudioDeliver, QwenStudioSaveDelivery,)}
__all__ = ['CATEGORY', 'PRESETS', 'ATTENTION_BACKENDS', 'UPSCALER_CACHE', 'model_file_identity', 'unload_owned_model', 'UpscalerCache', 'with_attention', 'image_tensor', 'resize', 'resize_rgba', 'match_batch', 'protection_mask', 'QwenStudioProtection', 'QwenStudioMaskPolicy', 'QwenStudioRestoreProtected', 'QwenStudioDeliveryPreset', 'delivery_geometry', 'layout', 'QwenStudioLayoutPreview', 'QwenStudioDeliver', 'safe_component', 'QwenStudioSaveDelivery']
