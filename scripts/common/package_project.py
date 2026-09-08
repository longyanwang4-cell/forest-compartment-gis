#!/usr/bin/env python3
"""Package workflow outputs without following links or leaking local debug paths.

`delivery` mode is intended for sharing with students/teachers. It excludes raw
provenance, decision traces, error memory, normalized configs, and other files
that may contain local usernames or absolute paths. `full` mode is a local debug
archive and should not be shared without review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[2]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from forestgis_core.path_safety import assert_no_link_components, iter_safe_files  # noqa: E402

SKIP_SUFFIXES = {'.lock', '.tmp', '.bak', '.pyc'}
SKIP_DIRS = {'__pycache__'}
TEXT_REPORT_SUFFIXES = {'.json', '.jsonl', '.txt', '.md', '.html', '.htm', '.csv', '.xml', '.log'}
DELIVERY_REPORT_DENYLIST = {
    'provenance.json',
    'error_memory.jsonl',
    'decision_trace.jsonl',
    'normalized_config.json',
    'tool_registry_snapshot.json',
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def allowed(path: Path, output: Path) -> bool:
    try:
        if path.resolve() == output.resolve():
            return False
    except OSError:
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.suffix.lower() in SKIP_SUFFIXES or path.name.endswith('.lock'):
        return False
    return path.is_file() and not path.is_symlink()


def collect(root: Path, mode: str, output: Path) -> list[Path]:
    if mode == 'full':
        return sorted(p for p in iter_safe_files(root) if allowed(p, output))
    files: list[Path] = []
    project_data = root / '02_ProjectData'
    if project_data.exists():
        files.extend(p for p in iter_safe_files(project_data) if allowed(p, output))
    _, binary_reports = sanitized_report_payloads(root)
    files.extend(p for p in binary_reports if allowed(p, output))
    return sorted(set(files))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}



WINDOWS_ABS_RE = re.compile(r"(?i)(?:[a-z]:[\\/])[^\"'\r\n<>|]*")
UNC_ABS_RE = re.compile(r"(?:\\\\|//)[^\"'\r\n<>|]+")
POSIX_PRIVATE_RE = re.compile(r"/(?:home|users|mnt|tmp|var/tmp)/[^\"'\r\n<>|]*", re.IGNORECASE)


def redact_text(text: str, sensitive_roots: list[str] | None = None) -> str:
    result = text
    for value in sorted((sensitive_roots or []), key=len, reverse=True):
        if value:
            result = result.replace(value, '<LOCAL_PATH>')
            result = result.replace(value.replace('\\\\', '/'), '<LOCAL_PATH>')
    result = WINDOWS_ABS_RE.sub('<LOCAL_PATH>', result)
    result = UNC_ABS_RE.sub('<LOCAL_PATH>', result)
    result = POSIX_PRIVATE_RE.sub('<LOCAL_PATH>', result)
    return result


def redact_value(value: Any, sensitive_roots: list[str] | None = None) -> Any:
    if isinstance(value, str):
        return redact_text(value, sensitive_roots)
    if isinstance(value, list):
        return [redact_value(x, sensitive_roots) for x in value]
    if isinstance(value, dict):
        return {k: redact_value(v, sensitive_roots) for k, v in value.items()}
    return value


def sanitized_report_payloads(root: Path) -> tuple[dict[str, bytes], list[Path]]:
    reports = root / '03_Reports'
    payloads: dict[str, bytes] = {}
    binary_files: list[Path] = []
    if not reports.exists():
        return payloads, binary_files
    sensitive = [str(root), str(root.parent), str(Path.home())]
    for path in iter_safe_files(reports):
        if not allowed(path, root / '__not_an_output__.zip') or path.name in DELIVERY_REPORT_DENYLIST:
            continue
        rel = path.relative_to(root).as_posix()
        if path.suffix.lower() not in TEXT_REPORT_SUFFIXES:
            binary_files.append(path)
            continue
        raw = path.read_bytes()
        had_bom = raw.startswith(b'\xef\xbb\xbf')
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            binary_files.append(path)
            continue
        if path.suffix.lower() == '.json':
            try:
                value = json.loads(text)
                text = json.dumps(redact_value(value, sensitive), ensure_ascii=False, indent=2)
            except Exception:
                text = redact_text(text, sensitive)
        else:
            text = redact_text(text, sensitive)
        encoded = text.encode('utf-8')
        if had_bom:
            encoded = b'\xef\xbb\xbf' + encoded
        payloads[rel] = encoded
    return payloads, binary_files

def public_workflow_payloads(root: Path) -> dict[str, bytes]:
    """Create redacted workflow files for the delivery archive only."""
    workflow = root / '00_Workflow'
    summary = load_json(workflow / 'workflow_summary.json')
    state = load_json(workflow / 'workflow_state.json')
    manifest = load_json(workflow / 'input_manifest.json')

    sensitive = [str(root), str(root.parent), str(Path.home())]
    public_summary = {
        'schema_version': '1.0',
        'status': summary.get('status') or state.get('status'),
        'execution_mode': summary.get('execution_mode') or state.get('execution_mode'),
        'original_inputs_modified': bool(summary.get('original_inputs_modified', False)),
        'issues': redact_value(summary.get('issues') or state.get('issues') or [], sensitive),
        'artifacts': {
            'project_data': '02_ProjectData',
            'reports': '03_Reports',
            'manual_arcgis_guide': '03_Reports/ArcGISPro_手动创建小班项目.md',
        },
    }
    public_state = {
        'schema_version': state.get('schema_version', '1.0'),
        'workflow': state.get('workflow', 'prepare-practice'),
        'status': state.get('status'),
        'execution_mode': state.get('execution_mode'),
        'completed_steps': state.get('completed_steps') or [],
        'review_steps': state.get('review_steps') or [],
        'current_step': state.get('current_step'),
        'resume_count': state.get('resume_count', 0),
        'issues': redact_value(state.get('issues') or [], sensitive),
        'recommended_next_action': state.get('recommended_next_action'),
    }
    public_files = []
    for item in manifest.get('files') or []:
        if not isinstance(item, dict):
            continue
        public_files.append({
            key: redact_value(value, sensitive)
            for key, value in item.items()
            if key not in {'path'}
        })
    public_manifest = {
        'schema_version': manifest.get('schema_version', '1.0'),
        'summary': manifest.get('summary') or {},
        'warnings': manifest.get('warnings') or [],
        'security': manifest.get('security') or {},
        'files': public_files,
    }

    def encoded(value: dict[str, Any]) -> bytes:
        return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')

    return {
        '00_Workflow/workflow_summary.json': encoded(public_summary),
        '00_Workflow/workflow_state.json': encoded(public_state),
        '00_Workflow/input_manifest.json': encoded(public_manifest),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', required=True, help='工作流输出根目录')
    ap.add_argument('--output', required=True)
    ap.add_argument('--mode', choices=('delivery', 'full'), default='full')
    args = ap.parse_args()

    assert_no_link_components(args.project)
    assert_no_link_components(args.output)
    root = Path(args.project).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise RuntimeError('项目目录不存在或不是文件夹: %s' % root)
    files = collect(root, args.mode, output)
    public_files = {}
    if args.mode == 'delivery':
        public_files.update(public_workflow_payloads(root))
        report_payloads, _ = sanitized_report_payloads(root)
        public_files.update(report_payloads)
    if not files and not public_files:
        raise RuntimeError('没有可打包文件: %s' % root)

    entries = []
    for p in files:
        rel = p.relative_to(root).as_posix()
        entries.append({'path': rel, 'size': p.stat().st_size, 'sha256': sha256(p)})
    for rel, content in public_files.items():
        entries.append({'path': rel, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
    entries.sort(key=lambda item: item['path'])
    manifest_text = '\n'.join(f"{x['sha256']}  {x['path']}" for x in entries) + '\n'
    manifest_json = {
        'schema_version': '1.1',
        'mode': args.mode,
        'root_name': root.name,
        'file_count': len(entries),
        'privacy_note': 'delivery mode excludes raw local paths, provenance, decision traces, and error memory',
        'files': entries,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    arc_root = root.name
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in files:
            zf.write(p, arcname=f"{arc_root}/{p.relative_to(root).as_posix()}")
        for rel, content in sorted(public_files.items()):
            zf.writestr(f'{arc_root}/{rel}', content)
        zf.writestr(f'{arc_root}/MANIFEST_SHA256.txt', manifest_text.encode('utf-8'))
        zf.writestr(
            f'{arc_root}/MANIFEST_DELIVERY.json',
            json.dumps(manifest_json, ensure_ascii=False, indent=2).encode('utf-8'),
        )
        readme = (
            '森林经理学实习 GIS 成果包\n\n'
            '02_ProjectData：ArcGIS Pro 可编辑数据和工具箱\n'
            '03_Reports：质量检查、学生HTML报告、外业模板和手动创建项目说明\n'
            '00_Workflow：已脱敏的工作流摘要、状态和输入清单\n'
            'MANIFEST_SHA256.txt：文件完整性校验\n\n'
            '注意：本交付包默认不包含本机绝对路径、原始provenance、错误记忆或决策轨迹。\n'
        )
        zf.writestr(f'{arc_root}/成果包说明.txt', readme.encode('utf-8'))
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
