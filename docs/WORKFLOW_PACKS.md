# Workspace and workflow-pack layout

Install one Luminaire Edit Studio repository as a ComfyUI custom node pack.
Choose a [supported workflow pack](../workflow_packs/README.md) for generation.

| Source | Purpose |
| --- | --- |
| `workspace_manifest.json` | Workspace name/version, shared runtime files and supported-pack registry |
| `luminaire/shared.py` | Model-independent image, mask, protection, delivery, cache and attention tools |
| `luminaire/engines/qwen21.py` | Qwen Quality/Draft policy, checkpoint selection, sigma adapter and clip routing |
| `nodes.py` / `__init__.py` | ComfyUI registration and stable legacy import/node IDs |
| `workflow_packs/qwen21/pack.json` | Qwen assets, capabilities, limits and runtime source |
| `workflow_packs/qwen21/` | Canonical Qwen canvas, task manifest, API templates and enhancer instructions |
| `tools/luminaire_batch.py` | Public batch entry point, using the established runner/state format |

The Qwen pack is the only generation engine included today. Shared tools can be
connected to images from other workflows without loading a Qwen model. Shared
tools alone do not adapt conditioning or sampling for an unsupported checkpoint.

## Compatibility paths

Existing `QwenStudio*` node IDs and the `tools/qwen_batch.py` command remain valid.
Root `QWEN_IMAGE_21_STUDIO.json`, `workflow_manifest.json`, `api/` and `prompts/`
are generated compatibility copies of canonical Qwen pack assets. Their contents
are checked before packaging; retaining them avoids breaking existing commands.

Edit the canonical pack files. From the repository root, run:

```powershell
python scripts/sync_prompts.py
python scripts/sync_packs.py --check
```

The first command refreshes embedded enhancer text and compatibility copies. If
only non-prompt assets changed, `python scripts/sync_packs.py` refreshes the copies.
Both commands accept `--check` for read-only verification. New API paths are shown
in the [Qwen pack guide](../workflow_packs/qwen21/README.md).

The installer accepts `-Pack qwen21`, installs shared code plus the selected
engine, and writes a versioned workflow under `user/default/workflows/Luminaire Edit Studio/`.
It refuses existing Luminaire and legacy Studio runtimes so duplicate node IDs
cannot be introduced by the helper. Existing installed workflows continue to use
their stable IDs after replacing the runtime.

## Additional packs

A new pack needs its own engine implementation and canonical assets, a registry
entry, capability/limit declarations, dependencies and validation evidence. Model
files remain separate downloads with their own licenses. The pack registry is
data for reviewed built-in packs, not a downloader or arbitrary code loader.
Only tested support should appear in the public support table. Existing workspace
contracts should remain stable when an engine is added.
