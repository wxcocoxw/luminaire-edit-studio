# SPDX-License-Identifier: GPL-3.0-only
"""Standard-library helpers for the workspace's workflow-pack registry."""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LEGACY_TARGETS = {'QWEN_IMAGE_21_STUDIO.json', 'workflow_manifest.json', 'api', 'prompts'}


def project_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError(f'Invalid project-relative path: {relative}')
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError(f'Path escaped the source root: {relative}')
    return resolved


def load_workspace():
    workspace = json.loads((ROOT / 'workspace_manifest.json').read_text(encoding='utf-8'))
    if workspace.get('format_version') != 1:
        raise ValueError('Unsupported workspace manifest format.')
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', workspace['package_slug']):
        raise ValueError('Invalid package slug.')
    packs = []
    seen = set()
    for entry in workspace['packs']:
        if entry['id'] in seen or not re.fullmatch(r'[a-z0-9_-]+', entry['id']):
            raise ValueError('Invalid or duplicate workflow-pack ID.')
        seen.add(entry['id'])
        manifest_path = project_path(entry['manifest'])
        pack = json.loads(manifest_path.read_text(encoding='utf-8'))
        if pack.get('format_version') != 1 or pack['id'] != entry['id']:
            raise ValueError('Workflow-pack registry/manifest mismatch.')
        for field in ('workflow', 'workflow_manifest', 'api_directory', 'legacy_api_directory'):
            if not project_path(pack[field]).exists():
                raise ValueError(f'Missing pack asset: {pack[field]}')
        for relative in [*pack['prompt_sources'].values(), *pack['runtime_files']]:
            if not project_path(relative).is_file():
                raise ValueError(f'Missing pack source: {relative}')
        workflow_manifest = json.loads(project_path(pack['workflow_manifest']).read_text(encoding='utf-8'))
        if workflow_manifest['build'] != pack['version'] or list(workflow_manifest['tasks']) != pack['tasks']:
            raise ValueError('Pack version/tasks disagree with its workflow manifest.')
        packs.append(pack)
    if workspace['default_pack'] not in seen:
        raise ValueError('Default workflow pack is not registered.')
    for relative in workspace['shared_runtime_files']:
        if not project_path(relative).is_file():
            raise ValueError(f'Missing shared runtime source: {relative}')
    return workspace, packs


def compatibility_pairs(pack):
    pack_root = project_path(f"workflow_packs/{pack['id']}")
    for alias in pack.get('compatibility_copies', []):
        if alias['target'] not in LEGACY_TARGETS:
            raise ValueError('Refusing to overwrite a non-legacy source path.')
        source, target = project_path(alias['source']), project_path(alias['target'])
        if not source.is_relative_to(pack_root):
            raise ValueError('Compatibility source must belong to its workflow pack.')
        if source.is_dir():
            for path in sorted(source.rglob('*')):
                if path.is_file() and (path.suffix in ('.json', '.txt') or path.name == 'README.md'):
                    yield path, target / path.relative_to(source)
        else:
            yield source, target


def synchronize_compatibility(packs, *, check=False):
    stale = []
    for pack in packs:
        for source, target in compatibility_pairs(pack):
            content = source.read_bytes()
            if not target.is_file() or target.read_bytes() != content:
                stale.append(target.relative_to(ROOT).as_posix())
                if not check:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
    return stale
