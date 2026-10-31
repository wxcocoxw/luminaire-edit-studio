# License scope and third-party notices

Luminaire Edit Studio's original project code, documentation, enhancer instructions
and workflow contributions are licensed under **GPL-3.0-only**. The full license
text is in [LICENSE](LICENSE). This grant does not include a later GPL version.

The workflow uses separately installed ComfyUI and external nodes. Calling those
implementations does not make them project-authored code. No model weights,
third-party node implementations, original Patreon download, example source
images or research-licensed enhancer instructions are bundled.

## ComfyUI

[ComfyUI](https://github.com/Comfy-Org/ComfyUI) is distributed under GPL version 3.
The six-step compatibility adapter calls the installed host's
`comfy.model_sampling.flux_time_shift`; it does not embed Viggle's implementation.
ComfyUI's authors retain their rights in the host code.

## ComfyUI workflow templates

Native model wiring and serialization were developed with reference to
[Comfy-Org's workflow templates](https://github.com/Comfy-Org/workflow_templates).
The retained upstream notice is in
[licenses/Comfy-Workflow-Templates-MIT.txt](licenses/Comfy-Workflow-Templates-MIT.txt).
It applies to upstream MIT material, not to model weights or separately licensed
prompt files. Project modifications are under GPL-3.0-only.

## Historical credit and compatibility

Aitrepreneur's ULTRA workflow was the historical starting point for this project.
The supplied download is not included. The project's task groups, modules and
layout were assembled by its own builder; inherited long enhancer instructions
were replaced for 1.3.3. Credit is historical attribution, not a permission grant
or an endorsement. See [Sources](SOURCES.md) and the
[model licensing notes](docs/MODEL_LICENSES.md).

Existing `QwenStudio*` node IDs, extension paths and workflow filenames remain for
saved-workflow compatibility. The primary display name is Luminaire Edit Studio.
Qwen and Viggle names describe supported external models and their recipes; no
trademark rights or upstream endorsement are claimed.

Models, adapters and external packages retain their own publishers' terms. A
GPL license for this integration does not grant commercial rights to a model.
