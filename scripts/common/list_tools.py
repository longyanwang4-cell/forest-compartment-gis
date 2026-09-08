#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from forestgis_core.tool_registry import ToolRegistry

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--registry', default=str(ROOT/'registry'/'tool_registry.json'))
    ap.add_argument('--output')
    args = ap.parse_args()
    data = ToolRegistry.load(args.registry).to_dict()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        p = Path(args.output); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding='utf-8')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
