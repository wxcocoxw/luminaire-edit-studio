# SPDX-License-Identifier: GPL-3.0-only
"""Create a source release archive, or a separately labeled review preview."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import json
import re
import subprocess
import sys
import zipfile

from packs import load_workspace

ROOT=Path(__file__).resolve().parents[1]
PUBLIC_FILES=('__init__.py','nodes.py','README.md','CHANGELOG.md','SOURCES.md',
              '.gitignore','.gitattributes','LICENSE','NOTICE.md','INSTALL_STUDIO.ps1',
              'INSTALL_STUDIO_DEPENDENCIES.bat','QWEN_IMAGE_21_STUDIO.json',
              'workflow_manifest.json','tools/qwen_batch.py','scripts/package_release.py',
              'scripts/sync_prompts.py','scripts/packs.py','scripts/sync_packs.py',
              'tools/luminaire_batch.py','workspace_manifest.json',
              'licenses/Comfy-Workflow-Templates-MIT.txt')
PUBLIC_DIRS=('luminaire','workflow_packs','web','api','docs','prompts','licenses')
BLOCKED_DIRS={'test','tests','validation','fixtures','benchmarks','handoff','security-audits','audit_reports',
              '.agents','.codex','.claude','.cursor','__pycache__'}
BLOCKED_FILES={'docs/releasing.md','docs/licensing_review.md'}
BLOCKED_REPORTS={'run-metadata.json','coverage-ledger.json','needs-validation.md'}
ALLOWED_EXTENSIONS={'.py','.js','.json','.md','.txt','.ps1','.bat'}


def blocked(path:Path)->bool:
    parts=[p.lower() for p in path.parts]
    name=parts[-1]
    return (path.as_posix().lower() in BLOCKED_FILES
            or name in BLOCKED_REPORTS or name.startswith('findings')
            or any(part in BLOCKED_DIRS for part in parts)
            or name.startswith(('test_','codex','start_codex','.env'))
            or bool(re.search(r'(_test\.|\.test\.|\.spec\.)',name))
            or 'handoff' in name or (name.startswith('ai_') and path.suffix.lower() in ('.md','.txt')) or (name.endswith('.md') and ('agent' in name or name in ('claude.md','gemini.md','skill.md'))))


def public_files()->list[Path]:
    candidates={ROOT/name for name in PUBLIC_FILES if (ROOT/name).is_file()}
    for directory in PUBLIC_DIRS:
        if not (ROOT/directory).is_dir():continue
        candidates.update(p for p in (ROOT/directory).rglob('*') if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS)
    chosen=[]
    for path in sorted(candidates):
        relative=path.relative_to(ROOT)
        if blocked(relative):continue
        if not path.resolve().is_relative_to(ROOT.resolve()) or path.is_symlink():
            raise ValueError(f'Public file resolves outside the source root or is a symlink: {relative}')
        chosen.append(path)
    if (ROOT/'.git').exists() and chosen:
        # Honor actual ignore rules even for accidentally force-added files.
        names=[p.relative_to(ROOT).as_posix() for p in chosen]
        check=subprocess.run(['git','check-ignore','--no-index','-z','--stdin'],
                             input=('\0'.join(names)+'\0').encode(),cwd=ROOT,capture_output=True)
        if check.returncode not in (0,1):raise RuntimeError(check.stderr.decode(errors='replace'))
        ignored=set(check.stdout.decode().strip('\0').split('\0'))
        chosen=[p for p in chosen if p.relative_to(ROOT).as_posix() not in ignored]
    return chosen


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview',action='store_true',help='Build an explicitly labeled review preview.')
    args=parser.parse_args()
    manifest,packs=load_workspace()
    version=manifest['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?',version):
        parser.error('Invalid release version.')
    license_path=ROOT/'LICENSE'
    if not args.preview and (not license_path.is_file() or not license_path.read_text(encoding='utf-8').strip()):
        parser.error('Final release requires a selected LICENSE. Use --preview for the review archive.')
    if manifest.get('license')!='GPL-3.0-only':
        parser.error('Manifest must declare the selected GPL-3.0-only license.')
    sync=subprocess.run([sys.executable,str(ROOT/'scripts/sync_prompts.py'),'--check'],
                        cwd=ROOT,capture_output=True,text=True)
    if sync.returncode:
        parser.error('Enhancer sources are out of sync: '+sync.stdout.strip()+sync.stderr.strip())
    files=public_files()
    for required in PUBLIC_FILES:
        if required=='LICENSE' and args.preview:continue
        if ROOT/required not in files:parser.error(f'Missing or ignored public file: {required}')
    required_assets=list(manifest['shared_runtime_files'])+[entry['manifest'] for entry in manifest['packs']]
    for pack in packs:
        required_assets.extend([pack['workflow'],pack['workflow_manifest'],
                                *pack['runtime_files'],*pack['prompt_sources'].values()])
        required_assets.extend(p.relative_to(ROOT).as_posix()
                               for p in (ROOT/pack['legacy_api_directory']).rglob('*.json'))
    for required in required_assets:
        if ROOT/required not in files:parser.error(f'Missing or ignored pack source: {required}')
    for path in files:
        if path.suffix=='.json':json.loads(path.read_text(encoding='utf-8'))
    suffix='-preview' if args.preview else ''
    folder=f"{manifest['package_slug']}-v{version}{suffix}"
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    target=dist/(folder+'.zip')
    checks=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(ROOT).as_posix()+'\n' for p in files)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in files:archive.write(path,folder+'/'+path.relative_to(ROOT).as_posix())
        archive.writestr(folder+'/SHA256SUMS.txt',checks)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:raise RuntimeError('ZIP CRC check failed.')
        for line in checks.splitlines():
            digest,name=line.split('  ',1)
            if hashlib.sha256(archive.read(folder+'/'+name)).hexdigest()!=digest:raise RuntimeError(f'ZIP hash mismatch: {name}')
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(digest+'  '+target.name+'\n',encoding='utf-8')
    print(f'{target}\n{len(files)} public files + SHA256SUMS.txt; {target.stat().st_size:,} bytes\nSHA256 {digest}')
    return 0


if __name__=='__main__':raise SystemExit(main())
