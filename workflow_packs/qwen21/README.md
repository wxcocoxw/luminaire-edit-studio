# Qwen Image 2.1 workflow pack

**Luminaire Edit Studio 1.4.0 · pack ID `qwen21`.** This is the first supported
generation pack. It preserves the existing Qwen generation recipe and eight tasks.

1. Install the [Luminaire node pack](../../README.md#installation) once.
2. Install the native/external nodes and model files in [Dependencies](../../docs/DEPENDENCIES.md).
3. Restart ComfyUI, refresh its browser tab, and import
   [QWEN_IMAGE_21_STUDIO.json](QWEN_IMAGE_21_STUDIO.json).
4. Select installed models and source files. Keep the default Quality mode for a
   first edit. Use the [usage guide](../../docs/USAGE.md) for masks and references.

| Feature | Included behavior / limits |
| --- | --- |
| Image Edit | Source first; additional references follow in order. Optional protection and alignment. |
| Masked Edit | Explicit mask polarity, crop/context and stitching. |
| Outpaint | Padded canvas and source context, followed by stitching. |
| Folder Batch | Separate inputs with shared settings; [CLI](api/README.md) supports resumable jobs. |
| Transparent Assets | RGBA conditioning and source/generated alpha policy. |
| Text to Image | Explicit dimensions; separate optional text prompt enhancer. |
| Upscale Single / Folder | Shared finishing tools; no Qwen model or sampling needed. |
| Draft | Viggle v0.2.1 merged checkpoint, six steps, at most three total input images; bypasses Quality LoRAs and ControlNet. |

Quality defaults remain 40 steps, CFG 1, Euler/simple and denoise 1. The default
working budget is approximately 2 MP; explicit T2I dimensions remain separate.
See [support and validation scope](../../docs/SUPPORT.md).

The [manifest](pack.json) locates this pack's canvas, task manifest, API templates,
enhancer sources and engine implementation. Its Python engine is
[luminaire/engines/qwen21.py](../../luminaire/engines/qwen21.py).
Canonical templates are in [api/v1_3](api/v1_3); [api](api) retains legacy variants.

Existing root workflow/API/prompt paths remain compatibility copies. Edit the
canonical pack assets and synchronize them using the [pack guide](../../docs/WORKFLOW_PACKS.md).
Existing node IDs and batch state formats remain supported.

Project contributions are GPL-3.0-only; [model licenses remain separate](../../docs/MODEL_LICENSES.md).
Models and third-party node implementations are not included in this pack.
