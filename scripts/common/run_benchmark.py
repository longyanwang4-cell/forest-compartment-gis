#!/usr/bin/env python3
"""Small deterministic benchmark for request contracts and agent adapters.
This does not replace real ArcPy or student usability testing.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from forestgis_core.contracts import CommandRequest, ContractError

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--scenarios',default=str(ROOT/'benchmarks'/'scenarios'/'core_scenarios.json')); ap.add_argument('--output'); args=ap.parse_args()
    cases=json.loads(Path(args.scenarios).read_text(encoding='utf-8-sig')).get('scenarios') or []
    results=[]; passed=0
    started=time.time()
    for case in cases:
        ok=False; actual=None; error=None
        try:
            req=CommandRequest.from_mapping(case['request'],platform=case.get('platform'))
            actual=req.command.value
            ok=bool(case.get('expected_ok')) and (not case.get('expected_command') or actual==case['expected_command'])
        except (ContractError,ValueError,TypeError) as exc:
            error=str(exc); ok=not bool(case.get('expected_ok'))
        passed+=int(ok)
        results.append({'id':case['id'],'passed':ok,'actual_command':actual,'error':error})
    report={'schema_version':'1.0','total':len(cases),'passed':passed,'failed':len(cases)-passed,'score':passed/len(cases) if cases else 0,'elapsed_seconds':round(time.time()-started,4),'scope':'contract-and-adapter-only','results':results}
    text=json.dumps(report,ensure_ascii=False,indent=2); print(text)
    if args.output:
        p=Path(args.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding='utf-8')
    return 0 if passed==len(cases) else 2
if __name__=='__main__': raise SystemExit(main())
