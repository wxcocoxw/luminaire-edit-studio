# Sources and credits

Luminaire Edit Studio's original contributions are licensed under GPL-3.0-only.
See [LICENSE](LICENSE), [NOTICE](NOTICE.md), and the
[model licensing notes](docs/MODEL_LICENSES.md).

## Historical workflow credit

The historical starting point was the supplied
`QWEN-IMAGE-EDIT-21_ULTRA_WORKFLOW.json`, credited to
[Aitrepreneur](https://www.patreon.com/aitrepreneur). That original download is not
included. Studio's builder assembles its own task modules and layout; inherited
upstream enhancer text was replaced in 1.3.3. Attribution is historical credit,
not an assertion of upstream permission or endorsement.

## Runtime and workflow references

- [ComfyUI](https://github.com/Comfy-Org/ComfyUI): native conditioning/cache,
  sampling, model management, attention dispatch, upscaling and PNG output.
  The Draft adapter calls its GPL `comfy.model_sampling.flux_time_shift` primitive from `luminaire/engines/qwen21.py`.
- [ComfyUI frontend](https://github.com/Comfy-Org/ComfyUI_frontend): native subgraphs,
  promoted widgets and prompt export.
- [Official workflow templates](https://github.com/Comfy-Org/workflow_templates):
  native model wiring and serialized-node reference. The MIT notice is retained in
  [licenses/Comfy-Workflow-Templates-MIT.txt](licenses/Comfy-Workflow-Templates-MIT.txt).
- [Qwen Image 2.1](https://huggingface.co/Qwen/Qwen-Image-2.1) and the
  [Comfy-Org catalog](https://huggingface.co/Comfy-Org/Qwen-Image-2.1): external model files.
- [Texture-fix VAE](https://huggingface.co/madebyollin/texture-fix-vae-for-qwen-image-2.1).
- [Viggle Turbo](https://huggingface.co/Viggle/Qwen-Image-2.1-viggle-turbo): external
  v0.2.1 merged six-step checkpoint. Its timestep values and resolution calibration
  are compatibility parameters. No Viggle runtime node or LoRA-hook code is bundled.
- [Comfy Kitchen](https://github.com/Comfy-Org/comfy-kitchen),
  [SageAttention](https://github.com/thu-ml/SageAttention),
  [Sage Windows builds](https://github.com/woct0rdho/SageAttention), and
  [Triton Windows](https://github.com/triton-lang/triton-windows).

The seven external node packs and their roles are listed in
[Dependencies](docs/DEPENDENCIES.md). Models, adapters and third-party implementations
are installed separately and keep their publishers' terms. No upstream endorsement
or transfer of trademark rights is implied.
