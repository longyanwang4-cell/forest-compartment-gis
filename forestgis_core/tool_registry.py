"""Schema-first GIS tool registry used by planners and model adapters."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ToolRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    id: str
    display_name: str
    runtime: str
    risk_level: str
    mutates_data: bool
    idempotent: bool
    description: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    mutates_original_inputs: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ToolSpec":
        required = ("id", "display_name", "runtime", "risk_level", "description")
        missing = [k for k in required if not value.get(k)]
        if missing:
            raise ToolRegistryError(f"工具定义缺少字段: {', '.join(missing)}")
        risk = str(value["risk_level"]).lower()
        if risk not in {"low", "medium", "high"}:
            raise ToolRegistryError(f"无效risk_level: {risk}")
        return cls(
            id=str(value["id"]),
            display_name=str(value["display_name"]),
            runtime=str(value["runtime"]),
            risk_level=risk,
            mutates_data=bool(value.get("mutates_data", False)),
            mutates_original_inputs=bool(value.get("mutates_original_inputs", False)),
            idempotent=bool(value.get("idempotent", False)),
            description=str(value["description"]),
            inputs=dict(value.get("inputs") or {}),
            outputs=dict(value.get("outputs") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "runtime": self.runtime,
            "risk_level": self.risk_level,
            "mutates_data": self.mutates_data,
            "mutates_original_inputs": self.mutates_original_inputs,
            "idempotent": self.idempotent,
            "description": self.description,
            "inputs": self.inputs,
            "outputs": self.outputs,
        }


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec], *, registry_version: str = "unknown") -> None:
        ids = [x.id for x in specs]
        dup = sorted({x for x in ids if ids.count(x) > 1})
        if dup:
            raise ToolRegistryError(f"重复工具ID: {dup}")
        if any(x.mutates_original_inputs for x in specs):
            raise ToolRegistryError("安全策略禁止任何工具声明可修改原始输入")
        self._specs = {x.id: x for x in specs}
        self.registry_version = registry_version

    @classmethod
    def load(cls, path: str | Path) -> "ToolRegistry":
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict) or not isinstance(value.get("tools"), list):
            raise ToolRegistryError("tool registry根节点或tools字段无效")
        specs = [ToolSpec.from_mapping(x) for x in value["tools"]]
        return cls(specs, registry_version=str(value.get("registry_version") or "unknown"))

    def get(self, tool_id: str) -> ToolSpec:
        try:
            return self._specs[tool_id]
        except KeyError as exc:
            raise ToolRegistryError(f"未注册工具: {tool_id}") from exc

    def list(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_version": self.registry_version,
            "tools": [x.to_dict() for x in self.list()],
        }
