"""Project-local error memory with deterministic pattern matching."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any
from .contracts import utc_now


def _load_rules(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return list(value.get('rules') or [])
    except Exception:
        return []


def classify_error(text: str, rules_path: Path) -> dict[str, Any]:
    lower = text.lower()
    for rule in _load_rules(rules_path):
        patterns = [str(x) for x in rule.get('patterns') or []]
        if any(p.lower() in lower for p in patterns):
            return {
                'code': rule.get('code', 'KNOWN_ERROR'),
                'suggestion': rule.get('suggestion', ''),
                'matched_pattern': next((p for p in patterns if p.lower() in lower), None),
            }
    return {'code': 'UNCLASSIFIED_ERROR', 'suggestion': '查看步骤stderr和docs/troubleshooting.md后再决定是否重试。'}


def append_error_memory(path: Path, *, step: str, exit_code: int, text: str, rules_path: Path) -> dict[str, Any]:
    info = classify_error(text, rules_path)
    normalized = ' '.join(text.strip().split())[:2000]
    record = {
        'timestamp': utc_now(),
        'step': step,
        'exit_code': int(exit_code),
        'signature': hashlib.sha256(normalized.encode('utf-8', errors='replace')).hexdigest()[:16],
        'message_excerpt': normalized[:600],
        **info,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    return record
