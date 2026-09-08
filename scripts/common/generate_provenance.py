#!/usr/bin/env python3
"""Generate a reproducibility/provenance record for a completed workflow."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, sys
from pathlib import Path
from datetime import datetime, timezone

SKILL_ROOT = Path(__file__).resolve().parents[2]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))
from forestgis_core.path_safety import assert_no_link_components, iter_safe_files

CHUNK = 1024 * 1024

def sha256_file(path: Path, mode: str) -> str:
    h = hashlib.sha256()
    size = path.stat().st_size
    with path.open('rb') as f:
        if mode == 'full' or size <= 2 * CHUNK:
            for block in iter(lambda: f.read(CHUNK), b''):
                h.update(block)
        elif mode == 'sampled':
            h.update(f.read(CHUNK))
            if size > CHUNK:
                f.seek(max(0, size-CHUNK)); h.update(f.read(CHUNK))
            h.update(str(size).encode())
        else:
            h.update(f'{path.name}|{size}|{path.stat().st_mtime_ns}'.encode())
    return h.hexdigest()

def file_record(path: Path, root: Path, mode: str) -> dict:
    st = path.stat()
    return {
        'path': str(path), 'relative_path': str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
        'size_bytes': st.st_size, 'mtime_ns': st.st_mtime_ns,
        'fingerprint_mode': mode, 'sha256': sha256_file(path, mode),
    }

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--workflow-root', required=True); ap.add_argument('--input-root', required=True)
    ap.add_argument('--output', required=True); ap.add_argument('--hash-mode', choices=['quick','sampled','full'], default='sampled')
    ap.add_argument('--skill-version', default='unknown'); args=ap.parse_args()
    assert_no_link_components(args.workflow_root); assert_no_link_components(args.input_root); assert_no_link_components(args.output)
    root=Path(args.workflow_root).resolve(); inp=Path(args.input_root).resolve(); out=Path(args.output).resolve()
    input_files=[]
    if inp.exists():
        for p in sorted(iter_safe_files(inp)):
            input_files.append(file_record(p, inp, args.hash_mode))
    step_files=[]
    steps=root/'00_Workflow'/'steps'
    if steps.exists():
        for p in sorted(steps.glob('*.json')):
            try: step_files.append(json.loads(p.read_text(encoding='utf-8-sig')))
            except Exception: pass
    outputs=[]
    for base in (root/'02_ProjectData', root/'03_Reports'):
        if base.exists():
            for p in sorted(iter_safe_files(base)):
                outputs.append(file_record(p, root, 'quick'))
    payload={
        'schema_version':'1.0', 'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'skill_version':args.skill_version, 'hash_mode':args.hash_mode,
        'environment':{'python':sys.version,'platform':platform.platform(),'machine':platform.machine(),'cwd':os.getcwd()},
        'input_root':str(inp),'workflow_root':str(root),'inputs':input_files,'steps':step_files,'outputs':outputs,
        'original_inputs_modified':False,
    }
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'SUCCESS','output':str(out),'input_files':len(input_files),'output_files':len(outputs)},ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
