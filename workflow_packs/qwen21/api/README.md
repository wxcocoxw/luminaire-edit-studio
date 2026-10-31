# API templates and resumable batching

Use `v1_3/` for Luminaire Edit Studio 1.4.0 · Qwen 2.1 pack. It contains 49 API/mapping pairs: 46 task/reference
variants and three Draft edit variants (source plus zero, one or two additional
references). The 46 pairs directly in `api/` are preserved legacy templates.

Each `*_api.json` has a matching `*_mapping.json`. API templates are executable
prompts; the main canvas JSON is a UI workflow and is not interchangeable with them.
Install the companion nodes and required native/external nodes on the server first.

## Example

From the repository root:

```powershell
python tools/luminaire_batch.py --template workflow_packs/qwen21/api/v1_3/edit_api.json --mapping workflow_packs/qwen21/api/v1_3/edit_mapping.json --input-dir "D:\images" --state-dir ".local/batches/example" --prompt "Make the background blue. Preserve the subject." --dry-run
```

Dry-run validates/enumerates without networking or manifest writes. Remove
`--dry-run` to upload and submit. The server defaults to `http://127.0.0.1:8188`;
override with `--server`. Add `--resume` to continue a started run with identical
settings. Use a new state directory after changing configuration. Failed jobs can
be retried with `--resume --retry-failed` using their recorded seeds.

For a remote server, use HTTPS to protect uploaded images, prompts and credentials.
Supply authentication through `--auth-env` rather than embedding a token in the URL
or command. Only use servers and custom nodes you trust.

## Selection and settings

- Edit: `edit_api.json`; add the numbered reference variant when using repeated
  `--reference` arguments. Reference order follows the mapping slots.
- Masked tasks: select the matching template and use `--mask-mode separate`,
  `--mask-dir`, and an optional `--mask-suffix`; alpha-mask templates are separate.
- Outpaint and RGBA edit: choose their matching template/mapping pairs.
- Finishing only: use `upscale_api.json` and its mapping.
- Draft: use `draft_edit_api.json` or the one/two-reference variants. The merged
  checkpoint and six-step recipe are selected by the sampler mode.

Edit `delivery_settings.inputs` in the selected template for delivery presets,
framing, alpha, grain, and project/version folders. Edit the sampler's optional
`attention_backend` for Auto/PyTorch/Comfy Kitchen INT8/SageAttention. The canvas's
live settings do not automatically change a separate API template.

Legacy CLI finishing flags (`--upscale`, `--scale`, `--grain`) run before Studio
exact sizing/grain. Keep one stage at its defaults to avoid applying an effect
twice. `--upscale ai` also needs an installed model selected with `--upscale-model`.
The runner records generation/grain seeds and durable state separately.

The runner uses Python 3.10+ and the standard library. It never installs software,
starts ComfyUI, modifies source images or cancels server-side jobs. Outputs are
saved by ComfyUI on its own filesystem. See `python tools/luminaire_batch.py --help`.
