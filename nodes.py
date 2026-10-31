# SPDX-License-Identifier: GPL-3.0-only
"""ComfyUI registration and legacy import surface for Luminaire Edit Studio.

Existing QwenStudio node IDs remain stable for saved workflows and API clients.
Shared tools and model-specific implementations live in separate modules.
"""
if __package__:
    from .luminaire import shared
    from .luminaire.engines import qwen21
else:
    from luminaire import shared
    from luminaire.engines import qwen21

for _module in (shared, qwen21):
    for _name in _module.__all__:
        globals()[_name] = getattr(_module, _name)

NODE_CLASS_MAPPINGS = {**shared.NODE_CLASS_MAPPINGS, **qwen21.NODE_CLASS_MAPPINGS}
NODE_DISPLAY_NAME_MAPPINGS = {
    name: name.replace('QwenStudio', 'Luminaire · ') for name in NODE_CLASS_MAPPINGS
}
