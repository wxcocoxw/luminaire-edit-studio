# Dependencies and model placement

## ComfyUI

Tested baseline: ComfyUI 0.42.0 / frontend 1.57.1, Python 3.13.11,
Torch 2.10.0+cu130, RTX 4090 24 GB and 64 GB RAM. Use ComfyUI's installation/update
procedure for your platform. Native Qwen 2.1 conditioning/cache, subgraphs, lazy
inputs, model attention overrides and targeted model unloading must be available.
No minimum version or lower-memory hardware guarantee is asserted.

The companion pack is this repository itself: root `__init__.py`, `nodes.py`,
and `web/studio.js`. Its Python imports use the host's Torch, NumPy and Pillow.
No separate pip requirements are needed for the Auto backend.

## External node packs

Install current versions providing the listed capabilities, then restart ComfyUI.

| Project | Canvas role |
| --- | --- |
| [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) | SetNode/GetNode Studio Bus; cross-subgraph lookup is required. |
| [ComfyUI-AusBoss](https://github.com/ausboss/ComfyUI-AusBoss) | Workflow Switches, Image Folder, source padding, crop and stitch. |
| [rgthree-comfy](https://github.com/rgthree/rgthree-comfy) | Power Lora Loader and Image Comparer. |
| [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) | BatchCount+ and ImageBatchMultiple+. |
| [Fantastic MiniMax H3 PromptBuilder](https://github.com/Adudeguyman/ComfyUI-Fantastic-MiniMaxH3-PromptBuilder) | Media loader/reference splitter; MiniMax model weights are not needed for those loader nodes. |
| [ComfyUI-PixelDriftFix](https://github.com/Mozer/ComfyUI-PixelDriftFix) | Optional RGB alignment. |
| [comfyui_controlnet_aux](https://github.com/Fannovel16/comfyui_controlnet_aux) | AIO_Preprocessor for optional structural guidance. |

These implementations are not bundled. Install through ComfyUI Manager where
available, or follow each project's own instructions.

The optional `INSTALL_STUDIO_DEPENDENCIES.bat` installs missing copies of these
seven packs and their requirements. For Windows Portable only, copy that BAT into
the inner ComfyUI folder (beside `main.py`) or portable root and run it with ComfyUI
closed. It selects the bundled interpreter and protects core GPU package versions.
It does not install the Studio companion nodes, download weights, update ComfyUI,
or update existing external node-pack copies. Review its output/logs before use.

## Core models

Download separately and select the filenames in the shared model subgraph.
Folders below are relative to ComfyUI.

| Role | File | Folder / publisher |
| --- | --- | --- |
| Quality | `qwen_image_2.1_int8_convrot.safetensors` | `models/diffusion_models/`; [Comfy-Org catalog](https://huggingface.co/Comfy-Org/Qwen-Image-2.1). |
| Encoder | `qwen3vl_8b_w4a8.safetensors` | `models/text_encoders/`; [encoder catalog](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/tree/main/text_encoders). |
| VAE | `texture_fix_vae_for_qwen_image_2.1_bf16.safetensors` | `models/vae/`; [texture-fix publisher](https://huggingface.co/madebyollin/texture-fix-vae-for-qwen-image-2.1). |
| Draft (optional) | `Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-int8_convrot.safetensors` | `models/diffusion_models/`; [Viggle catalog](https://huggingface.co/Viggle/Qwen-Image-2.1-viggle-turbo). |

The Draft recipe explicitly uses the retained **v0.2.1 six-step merged checkpoint**,
not the publisher's newer v0.3 default or a separate LoRA. Quality works without
the Draft checkpoint. A compatible alternative VAE or encoder can be selected,
but its quality/memory behavior must be tested separately.

## Feature-specific assets

| Feature | File or selection | Folder |
| --- | --- | --- |
| AI delivery | Any installed model supported by native UpscaleModelLoader | `models/upscale_models/` |
| Edit prompt enhancer | `qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors` | `models/text_encoders/` |
| T2I prompt enhancer | `qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors` | `models/text_encoders/` |
| Structural guidance | `qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors` | `models/model_patches/` |
| Quality adapters | The selected LoRA files | `models/loras/` |

The Qwen feature weights are listed in the [Comfy-Org model catalog](https://huggingface.co/Comfy-Org/Qwen-Image-2.1).
Preprocessors can have their own downloadable assets. Disabled optional branches
should not require their weights. Enable and select an optional asset deliberately;
filename references in the canvas do not mean weights are included.

## SageAttention

Sage is optional. The tested Windows combination was SageAttention 2.2.0 post6,
triton-windows 3.6.0.post26, and matching portable Python 3.13 headers. Those binaries
must not be assumed compatible with another Python/Torch/CUDA installation.
Follow the [Windows Sage maintainer](https://github.com/woct0rdho/SageAttention)
and [Triton Windows guidance](https://github.com/triton-lang/triton-windows).
The Studio installer does not alter Python packages or enable Sage globally.
Restart ComfyUI after a compatible package install, then choose the sampler backend.
See [Performance](PERFORMANCE.md) for the measured comparison and mask fallback.

## Licensing

Weights, adapters, code and external node packs keep their publishers' terms.
Qwen Image 2.1 and Viggle's model terms require separate authorization for
commercial use. Check each selected asset's license. See the
[model licensing notes](MODEL_LICENSES.md) for publisher sources and the GPL license
scope. No model weights are
distributed in source or release archives.
