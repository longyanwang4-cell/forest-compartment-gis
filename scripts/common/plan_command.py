#!/usr/bin/env python3
"""把平台请求转换为统一、可审计的执行计划；不执行 GIS 命令。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forestgis_core.contracts import CommandRequest, ContractError, ExitCode  # noqa: E402
from forestgis_core.planner import build_execution_plan  # noqa: E402


def create_plan(platform: str, payload: dict) -> dict:
    # This Codex package uses the documented, platform-neutral request contract.
    # The former multi-platform adapter package was not distributed, so importing
    # it made the otherwise read-only `plan` command unusable.
    request = CommandRequest.from_mapping(payload, platform=platform)
    plan = build_execution_plan(request, ROOT)
    return {
        "schema_version": "1.0",
        "request": request.to_dict(),
        "plan": plan.to_dict(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="森林小班 GIS 统一请求规划器（只读，不执行）")
    ap.add_argument("--platform", default="universal",
                    choices=["universal", "codex"])
    ap.add_argument("--request", required=True, help="请求 JSON 文件")
    ap.add_argument("--output", help="计划 JSON 输出路径")
    args = ap.parse_args()
    try:
        payload = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ContractError("请求 JSON 根节点必须是对象")
        result = create_plan(args.platform, payload)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
        print(text)
        # 规划成功本身返回 0；被规划命令的预期退出码保存在 plan.expected_exit_code。
        return int(ExitCode.SUCCESS)
    except (ContractError, ValueError, json.JSONDecodeError) as exc:
        error = {
            "schema_version": "1.0",
            "status": "INPUT_ERROR",
            "process_exit_code": int(ExitCode.INPUT_ERROR),
            "errors": [str(exc)],
        }
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return int(ExitCode.INPUT_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
