# SPDX-License-Identifier: GPL-3.0-only
"""Synchronize the product's enhancer instructions into its workflow/templates.

Run with --check to verify the copies without changing files. These are runtime
model instructions; local coding-agent instructions are excluded from releases.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from packs import load_workspace, project_path, synchronize_compatibility

ROOT = Path(__file__).resolve().parents[1]


def synchronize(value, prompts):
    changed = False
    if isinstance(value, dict):
        role = value.get('properties', {}).get('studio_prompt_role')
        if role is not None:
            if value.get('type') != 'PrimitiveStringMultiline' or role not in prompts:
                raise ValueError('Invalid workflow enhancer role.')
            text = prompts[role]
            for target, key in [(value['widgets_values'], 0), (value['widgets_values_named'], 'value')]:
                if target[key] != text:
                    target[key] = text
                    changed = True
        fields = value.get('_meta', {}).get('studio_prompt_fields', {})
        for field, role in fields.items():
            if role not in prompts or not isinstance(value.get('inputs', {}).get(field), str):
                raise ValueError('Invalid API enhancer role.')
            if value['inputs'][field] != prompts[role]:
                value['inputs'][field] = prompts[role]
                changed = True
        for child in value.values():
            changed = synchronize(child, prompts) or changed
    elif isinstance(value, list):
        for child in value:
            changed = synchronize(child, prompts) or changed
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    stale = []
    _, packs = load_workspace()
    for pack in packs:
        prompts = {role: project_path(relative).read_text(encoding='utf-8').strip()
                   for role, relative in pack['prompt_sources'].items()}
        paths = [project_path(pack['workflow']), *sorted(project_path(pack['legacy_api_directory']).rglob('*_api.json'))]
        for path in paths:
            data = json.loads(path.read_text(encoding='utf-8'))
            if synchronize(data, prompts):
                stale.append(path.relative_to(ROOT).as_posix())
                if not args.check:
                    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    stale.extend(synchronize_compatibility(packs, check=args.check))
    print(('Outdated: ' if args.check else 'Updated: ') + (', '.join(stale) or 'none'))
    return int(args.check and bool(stale))


if __name__ == '__main__':
    raise SystemExit(main())
