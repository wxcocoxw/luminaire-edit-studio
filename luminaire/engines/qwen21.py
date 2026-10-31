# SPDX-License-Identifier: GPL-3.0-only
"""Qwen Image 2.1 conditioning routes and sampler policy for Luminaire."""
from __future__ import annotations

import logging
from pathlib import Path
import weakref

import torch

from .. import shared

CATEGORY = shared.CATEGORY
ATTENTION_BACKENDS = shared.ATTENTION_BACKENDS
MODES = ["Quality", "Draft - Viggle 6-step"]
DRAFT_FILE = "Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-int8_convrot.safetensors"


class QwenStudioRenderMode:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"quality_megapixels": ("FLOAT", {"default": 2}),
                "mode": (MODES,), "draft_megapixels": ("FLOAT", {"default": 1, "min": .25, "max": 2, "step": .25})}}
    RETURN_TYPES = ("STRING", "FLOAT")
    RETURN_NAMES = ("render_mode", "working_megapixels")
    FUNCTION = "resolve"
    CATEGORY = CATEGORY

    def resolve(self, quality_megapixels, mode, draft_megapixels):
        return mode, draft_megapixels if mode == MODES[1] else quality_megapixels


def viggle_sigmas(latent):
    """Six-step checkpoint parameters applied by ComfyUI's GPL flow primitive.

    The function name remains compatible with local callers. No Viggle node
    implementation is bundled. See SOURCES.md for the host implementation.
    """
    from comfy.model_sampling import flux_time_shift

    spatial_scale = latent.get('downscale_ratio_spacial', 16) / 16
    height, width = (round(dimension * spatial_scale)
                     for dimension in latent['samples'].shape[-2:])
    resolution_shift = .5 + .4 * (height * width - 256) / (8192 - 256)
    schedule = torch.tensor((1, 15 / 16, 7 / 8, 3 / 4, 1 / 2, 1 / 4), dtype=torch.float64)
    result = torch.zeros(7, dtype=torch.float32)
    result[:6] = flux_time_shift(resolution_shift, 1.0, schedule)
    return result


class QwenStudioSampler:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL", {"lazy": True}), "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",), "latent_image": ("LATENT",),
            "mode": ("STRING", {"default": "Quality", "forceInput": True}),
            "seed": ("INT", {"default": 42, "min": 0, "max": 0xffffffffffffffff}),
            "steps": ("INT", {"default": 40, "min": 1, "max": 1000})},
            "optional": {"attention_backend": (ATTENTION_BACKENDS,)}}
    RETURN_TYPES = ("LATENT",)
    FUNCTION = "sample"
    CATEGORY = CATEGORY

    def check_lazy_status(self, mode, model=None, **kwargs):
        if mode == MODES[1] and getattr(self, '_quality_model_ref', None) is not None:
            previous = self._quality_model_ref()
            self._quality_model_ref = None
            if previous is not None:
                shared.unload_owned_model(previous)
                logging.info('[Luminaire Edit Studio] Unloaded quality transformer family for Draft.')
        if mode == MODES[0] and getattr(self, '_draft_model', None) is not None:
            # Release the draft branch before requesting the base loader. Keeping
            # two large transformers resident leaves too little Windows headroom.
            shared.unload_owned_model(self._draft_model)
            self._draft_model = None
            self._draft_identity = None
            logging.info('[Luminaire Edit Studio] Unloaded draft transformer family for Quality.')
        return ['model'] if mode == MODES[0] and model is None else []

    def sample(self, positive, negative, latent_image, mode, seed, steps, model=None, attention_backend='Auto'):
        import nodes
        if mode == MODES[0]:
            if model is None:
                raise ValueError('Quality requires the base MODEL input.')
            # Track without retaining another large CPU model. The native manager
            # also unloads all GPU clones when switching to the internal Draft loader.
            self._quality_model_ref = weakref.ref(model)
            return nodes.common_ksampler(shared.with_attention(model, attention_backend), seed, steps, 1., 'euler', 'simple', positive, negative, latent_image, denoise=1.)
        if mode != MODES[1]:
            raise ValueError(f'Unknown render mode: {mode}')
        if any(len(item[1].get('reference_latents', [])) > 3 for item in positive):
            raise ValueError('Viggle draft supports at most three total images. Reduce references or use Quality.')
        import folder_paths
        from comfy.samplers import sampler_object
        from comfy_extras.nodes_custom_sampler import SamplerCustom
        path = folder_paths.get_full_path('diffusion_models', DRAFT_FILE)
        if not path:
            raise ValueError(f'Draft checkpoint missing: {DRAFT_FILE}. Quality works without it.')
        stat = Path(path).stat()
        identity = (path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if getattr(self, '_draft_identity', None) != identity:
            if getattr(self, '_draft_model', None) is not None:
                shared.unload_owned_model(self._draft_model)
                self._draft_model = None
                self._draft_identity = None
            self._draft_model = nodes.UNETLoader().load_unet(DRAFT_FILE, 'default')[0]
            self._draft_identity = identity
        draft = shared.with_attention(self._draft_model.clone(), attention_backend)
        draft.model_options.setdefault('transformer_options', {})['qwen_image21_cache'] = {'device': 'auto', 'dtype': 'default'}
        result = SamplerCustom.execute(draft, True, seed, 1., positive, negative,
                                       sampler_object('euler'), viggle_sigmas(latent_image), latent_image)
        return (result[0],)


class QwenStudioClipRoute:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"clip": ("CLIP", {"lazy": True}),
                "plain_clip": ("CLIP", {"lazy": True}),
                "mode": ("STRING", {"default": "Quality", "forceInput": True})}}
    RETURN_TYPES = ("CLIP",)
    FUNCTION = "select"
    CATEGORY = CATEGORY

    def check_lazy_status(self, mode, clip=None, plain_clip=None):
        field = 'plain_clip' if mode == MODES[1] else 'clip'
        return [field] if (plain_clip if field == 'plain_clip' else clip) is None else []

    def select(self, mode, clip=None, plain_clip=None):
        return (plain_clip if mode == MODES[1] else clip,)


NODE_CLASS_MAPPINGS = {node.__name__: node for node in (QwenStudioRenderMode, QwenStudioSampler, QwenStudioClipRoute,)}
__all__ = ['MODES', 'DRAFT_FILE', 'viggle_sigmas', 'QwenStudioRenderMode', 'QwenStudioSampler', 'QwenStudioClipRoute']
