#!/usr/bin/env python3
"""运行森林经理学实习 GIS 一键准备工作流。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forestgis_core.contracts import ExitCode  # noqa: E402
from forestgis_core.workflow import PracticeWorkflow, WorkflowError  # noqa: E402


def load_config(path: str | None) -> dict:
    if not path:
        return {}
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise WorkflowError("工作流配置根节点必须是对象", ExitCode.INPUT_ERROR)
    return value


def main() -> int:
    ap = argparse.ArgumentParser(description="森林经理学实习 GIS 一键准备工作流")
    ap.add_argument("--input-root")
    ap.add_argument("--output-root")
    ap.add_argument("--config")
    ap.add_argument("--propy-bat")
    ap.add_argument("--mode", choices=["fast", "standard", "strict"], default=None)
    ap.add_argument("--dry-run", action="store_true", help="只生成可审计执行计划，不调用GIS工具")
    ap.add_argument("--approve-candidates", action="store_true", help="严格模式下确认已人工检查候选小班")
    ap.add_argument("--expected-compartment-count", type=int)
    ap.add_argument("--working-crs")
    ap.add_argument("--dem-z-unit")
    ap.add_argument("--z-factor", type=float)
    ap.add_argument("--dem-cell-size", type=float)
    ap.add_argument("--zip-output")
    ap.add_argument("--skip-package", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--revalidate", action="store_true", help="恢复时强制重新执行全部验证步骤")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
        if args.input_root:
            cfg["input_root"] = args.input_root
        if args.output_root:
            cfg["output_root"] = args.output_root
        if not cfg.get("input_root") or not cfg.get("output_root"):
            raise WorkflowError("必须提供 input_root 和 output_root", ExitCode.INPUT_ERROR)
        if args.mode:
            cfg["execution_mode"] = args.mode
        if args.approve_candidates:
            cfg["candidate_review_approved"] = True
        if args.expected_compartment_count is not None:
            cfg["expected_compartment_count"] = args.expected_compartment_count
        if args.working_crs:
            cfg["working_crs"] = args.working_crs
        terrain = cfg.setdefault("terrain", {})
        if args.dem_z_unit:
            terrain["dem_z_unit"] = args.dem_z_unit
        if args.z_factor is not None:
            terrain["z_factor"] = args.z_factor
        if args.dem_cell_size is not None:
            terrain["dem_cell_size"] = args.dem_cell_size
        package = cfg.setdefault("package", {})
        if args.skip_package:
            package["enabled"] = False
        if args.zip_output:
            package["zip_output"] = args.zip_output

        if not args.dry_run and not args.propy_bat:
            raise WorkflowError("非dry-run模式必须提供--propy-bat", ExitCode.ENVIRONMENT_ERROR)
        workflow = PracticeWorkflow(skill_root=ROOT, config=cfg, propy_bat=(args.propy_bat or "DRY_RUN"))
        if args.dry_run:
            plan = workflow.preview()
            print(json.dumps({"status":"DRY_RUN","process_exit_code":0,"plan":plan,"plan_file":str(workflow.paths.execution_plan_file)}, ensure_ascii=False, indent=2))
            return 0
        code = workflow.run(resume=(args.resume or args.revalidate), revalidate=args.revalidate)
        print(json.dumps({
            "status": "SUCCESS" if code == 0 else "PAUSED_FOR_REVIEW",
            "process_exit_code": code,
            "workflow_state": str(workflow.paths.state_file),
            "output_root": str(workflow.paths.root),
        }, ensure_ascii=False, indent=2))
        return code
    except WorkflowError as exc:
        print(json.dumps({
            "status": "ERROR",
            "process_exit_code": exc.exit_code,
            "errors": [str(exc)],
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return int(exc.exit_code)
    except Exception as exc:  # 保留完整失败，不伪装成功
        print(json.dumps({
            "status": "SCRIPT_ERROR",
            "process_exit_code": int(ExitCode.SCRIPT_ERROR),
            "errors": [f"{type(exc).__name__}: {exc}"],
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return int(ExitCode.SCRIPT_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
