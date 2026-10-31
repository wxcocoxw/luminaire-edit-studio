# Enhancer instructions

These project-authored instructions are covered by GPL-3.0-only. They are part of
the product's runtime prompting, not instructions for coding agents.

- `edit_enhancer.txt` clarifies an edit using the supplied images.
- `t2i_enhancer.txt` expands a text-to-image brief.

This directory is the Qwen pack's canonical enhancer source. Root `prompts/` is
a compatibility copy. The saved workflow embeds these files so it can be imported normally. After
editing a file, run `python scripts/sync_prompts.py`; use `--check` to verify the
serialized copies. Runtime ports, bypass behavior and enhancer settings are
unchanged. The new instructions can produce different enhanced wording and
images from older releases. Disabling the enhancer keeps the direct prompt path.
