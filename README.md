# Luminaire Edit Studio

A ComfyUI workspace for image editing, batch processing and final delivery.
Shared image tools are paired with model-specific workflow packs. Generation
currently supports **Qwen Image 2.1**.

**v1.4.0 · GPL-3.0-only**

## Features

- Image editing, masked edits, outpainting and text-to-image generation.
- Multiple image references and protected regions that retain source pixels.
- Transparent assets and control over the final alpha channel.
- Single-image and folder upscaling, exact output sizing, framing and grain.
- Optional six-step drafts and resumable batch processing.

The shared finishing tools can process existing images without Qwen sampling.
See the [support table](docs/SUPPORT.md) for capabilities and limits.

## Requirements

- ComfyUI with native Qwen Image 2.1 support.
- The [required custom nodes and model files](docs/DEPENDENCIES.md) for your pack.
- Sufficient GPU and system memory for your models, resolution and references.
  See [compatibility and tested hardware](docs/PERFORMANCE.md).

Models and external node packs are installed separately.

## Installation

1. Close ComfyUI.
2. Place this repository in `ComfyUI/custom_nodes/luminaire-edit-studio/`.
   Keep only one installed copy; move any previous installation outside
   `custom_nodes` before replacing it.
3. Install the [dependencies and models](docs/DEPENDENCIES.md).
4. Restart ComfyUI and refresh its browser tab.
5. Load the [Qwen 2.1 workflow](workflow_packs/qwen21/QWEN_IMAGE_21_STUDIO.json),
   then select your installed models and input images.

The [Qwen 2.1 pack guide](workflow_packs/qwen21/README.md) covers its features and
settings. Example input filenames are placeholders; source images are not included.

### Windows Portable helper

Alternatively, keep the repository outside ComfyUI and run this command from its
root with ComfyUI closed. Replace the example path with your inner ComfyUI folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALL_STUDIO.ps1 -ComfyRoot "D:\ComfyUI_windows_portable\ComfyUI" -Pack qwen21
```

The helper installs Luminaire Edit Studio and the selected workflow. Install the
required models and external node packs separately.

## First edit

1. Choose **Edit**, load a source image and describe the change.
2. Leave **Quality** selected for your first render.
3. To protect an area, paint white in the source mask editor and enable
   **Protect · white keeps original pixels**.
4. Choose the delivery size, framing, alpha and finishing settings.
5. Use **Preview mask/layout only** to check the layout, then queue the edit.

Raw and final results are saved separately as PNG files. Read the
[usage guide](docs/USAGE.md) for masked editing, references and transparency.

## Help

- **Missing nodes:** install the workspace and required custom nodes, then restart
  ComfyUI and refresh the browser. Loading a workflow JSON does not install nodes.
- **Low VRAM or slow edits:** reduce the working resolution or reference count;
  see the [performance guide](docs/PERFORMANCE.md).
- **Protected pixels changed:** resizing, alpha flattening and grain can change
  pixels after restoration. See the [usage guide](docs/USAGE.md).
- **Folder automation:** see the [batch and API guide](workflow_packs/qwen21/api/README.md).

## License and credits

Luminaire Edit Studio's original code, documentation and workflow contributions
are licensed under [GPL-3.0-only](LICENSE). Models, adapters and external packages
retain their own licenses; review the [model licensing notes](docs/MODEL_LICENSES.md#model-use)
before commercial use.

See [third-party notices](NOTICE.md) and [sources and credits](SOURCES.md).
