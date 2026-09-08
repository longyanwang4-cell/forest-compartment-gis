"""统一配置识别和 v1.1.0 旧配置兼容转换。"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .contracts import CommandName, ContractError

SCHEMA_VERSION = "1.0"


def load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError("配置文件根节点必须是对象")
    return value


def detect_legacy_config_kind(config: Mapping[str, Any]) -> str:
    if "project" in config and "data_root" in config:
        return "project"
    if "preliminary_compartments" in config:
        return "build-data"
    if "segmentation" in config and "input" in config:
        return "segment"
    if config.get("schema_version") and config.get("command"):
        return "unified"
    return "unknown"


def normalize_processing_config(
    config: Mapping[str, Any],
    *,
    command: str | CommandName | None = None,
) -> dict[str, Any]:
    """转为统一外壳；不改写旧脚本所需的 payload。"""
    source = deepcopy(dict(config))
    kind = detect_legacy_config_kind(source)
    command_value = (command.value if isinstance(command, CommandName) else CommandName(str(command).strip().lower().replace("_", "-")).value) if command is not None else None
    if kind == "unified":
        result = source
        result.setdefault("schema_version", SCHEMA_VERSION)
        result.setdefault("input_root", None)
        result.setdefault("output_root", None)
        result.setdefault("imagery", None)
        result.setdefault("dem", None)
        result.setdefault("boundary", None)
        result.setdefault("compartments", None)
        result.setdefault("backend", "common-python")
        result.setdefault("python_environment", {})
        result.setdefault("safety", {})
        result.setdefault("reports", {})
        result.setdefault("payload", {})
        result.setdefault("compatibility", {"source_format": "unified"})
        return result
    if kind == "unknown" and command_value is None:
        raise ContractError("无法识别配置类型，请显式指定 command")
    inferred = command_value or kind
    input_section = source.get("input") if isinstance(source.get("input"), Mapping) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "command": inferred,
        "input_root": source.get("input_root"),
        "output_root": source.get("output_root") or source.get("output_dir"),
        "imagery": input_section.get("imagery"),
        "dem": input_section.get("dem"),
        "boundary": input_section.get("boundary"),
        "compartments": source.get("preliminary_compartments"),
        "backend": "arcgis-pro" if inferred == "build-data" else "common-python",
        "python_environment": {},
        "payload": source,
        "safety": {
            "protect_original_inputs": True,
            "allow_existing_output": bool(source.get("allow_existing_output", False)),
        },
        "reports": {},
        "compatibility": {
            "source_format": f"v1.1.0-{kind}",
            "legacy_payload_preserved": True,
        },
    }


def to_legacy_payload(unified: Mapping[str, Any]) -> dict[str, Any]:
    """提取旧脚本可直接读取的 payload。"""
    if "payload" in unified:
        payload = unified["payload"]
        if not isinstance(payload, Mapping):
            raise ContractError("统一配置 payload 必须是对象")
        return deepcopy(dict(payload))
    # 允许原始 v1.1 配置直接穿透。
    kind = detect_legacy_config_kind(unified)
    if kind in {"segment", "build-data", "project"}:
        return deepcopy(dict(unified))
    raise ContractError("配置中不存在可用的 legacy payload")
