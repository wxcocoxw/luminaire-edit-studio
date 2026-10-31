# Supported packs and capabilities

Luminaire Edit Studio 1.4.0 includes one generation pack: **Qwen Image 2.1**.
Shared tools accept ordinary ComfyUI image/mask tensors. They do not encode a
different model's prompts, references or latents automatically.

| Capability | Shared workspace | Qwen 2.1 pack |
| --- | --- | --- |
| Pixel protection and restoration | Available as nodes | Integrated into Edit and Masked Edit |
| Mask polarity and layout previews | Available as nodes | Connected to supported mask/layout routes |
| Exact sizing, framing, alpha and seeded RGB grain | Available as delivery nodes | Applied after restoration/compositing |
| AI/Lanczos upscaling of existing images | Available; AI needs its own model | Upscale Single and Folder bypass Qwen |
| Image editing and multi-reference conditioning | Requires an engine | Included with native Qwen 2.1 encoding |
| Masked edit, outpaint and RGBA generation | Requires an engine | Included in the saved canvas |
| Text to image | Requires an engine | Included with explicit dimensions |
| Draft generation | Engine-specific | Viggle v0.2.1 merged six-step recipe; up to three total images |
| Resumable folder submission | CLI with compatible templates/mappings | 49 current and 46 legacy API/mapping pairs |
| Other generation engines | No adapter or workflow pack bundled | Qwen checkpoint swapping does not add another model family |

Draft bypasses Quality LoRAs/ControlNet. Its specialized masked/outpaint/RGBA
routes have not each received independent GPU validation in this release.
The dedicated edit/T2I enhancer checkpoints were not installed for the cleanup
review, so no new quality comparison of the project-authored enhancer text was run.

The GPU baseline is ComfyUI 0.42.0 / frontend 1.57.1, Python 3.13.11,
Torch 2.10.0+cu130, an RTX 4090 24 GB and 64 GB RAM. Published performance
measurements describe 1.3.2, not a new 1.4.0 benchmark. Other platforms/GPUs do not
have a validated support claim. See [Performance](PERFORMANCE.md).

The 1.4.0 changes separate shared code from the engine and update packaging and
display names. Saved task wiring, models, defaults, enhancer text, reference order,
sampler policy, raw/final routing and delivery behavior are preserved.
Outputs remain 8-bit PNG.

Adding a model pack requires that model's conditioning, latent/sampling policy,
feature limits and validation. Capabilities must be declared accurately in the
pack manifest and this support table before advertising a new engine.
