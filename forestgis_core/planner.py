"""把统一请求转换为可审计的执行计划；本模块本身不启动任何进程。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import ntpath
import os
from pathlib import Path
from typing import Any

from .contracts import CommandName, CommandRequest, ExitCode, RuntimeKind
from .tool_registry import ToolRegistry


def _join_user_path(base: str, *parts: str) -> str:
    # Windows 盘符/反斜杠路径使用 ntpath，其他路径使用当前系统规则。
    if (len(base) >= 2 and base[1] == ":") or "\\" in base:
        joined = ntpath.join(base, *parts)
        if "/" in base and "\\" not in base:
            return joined.replace("\\", "/")
        return joined
    return os.path.join(base, *parts)


def _tool_meta(root: Path, tool_id: str) -> dict[str, Any]:
    try:
        spec = ToolRegistry.load(root / "registry" / "tool_registry.json").get(tool_id)
        return {"tool_id": spec.id, "risk_level": spec.risk_level, "mutates_data": spec.mutates_data, "idempotent": spec.idempotent}
    except Exception:
        return {"tool_id": tool_id}


@dataclass(frozen=True)
class ExecutionStep:
    name: str
    runtime: RuntimeKind
    tool_id: str | None = None
    risk_level: str = "low"
    mutates_data: bool = False
    idempotent: bool = True
    script: str | None = None
    arguments: tuple[str, ...] = ()
    accepted_exit_codes: tuple[int, ...] = (0,)
    reports: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["runtime"] = self.runtime.value
        data["arguments"] = list(self.arguments)
        data["accepted_exit_codes"] = list(self.accepted_exit_codes)
        data["reports"] = list(self.reports)
        return data


@dataclass(frozen=True)
class ExecutionPlan:
    command: CommandName
    platform: str
    steps: tuple[ExecutionStep, ...] = ()
    expected_exit_code: int = ExitCode.SUCCESS
    disabled_reason: str | None = None
    legacy_compatible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def disabled(self) -> bool:
        return self.disabled_reason is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command.value,
            "platform": self.platform,
            "steps": [step.to_dict() for step in self.steps],
            "expected_exit_code": int(self.expected_exit_code),
            "disabled": self.disabled,
            "disabled_reason": self.disabled_reason,
            "legacy_compatible": self.legacy_compatible,
            "metadata": self.metadata,
        }


def build_execution_plan(request: CommandRequest, skill_root: str | Path) -> ExecutionPlan:
    """构造计划，不检查用户数据是否存在，也不执行脚本。"""
    root = Path(skill_root)
    common = root / "scripts" / "common"
    pro = root / "scripts" / "arcgis_pro"
    cmd = request.command

    if cmd is CommandName.PROJECT:
        return ExecutionPlan(
            command=cmd,
            platform=request.platform,
            expected_exit_code=ExitCode.EXPERIMENTAL_FEATURE_DISABLED,
            disabled_reason=(
                "automatic APRX creation is EXPERIMENTAL_DISABLED; "
                "use docs/ArcGISPro_手动创建小班项目.md"
            ),
            metadata={"manual_guide": "docs/ArcGISPro_手动创建小班项目.md"},
        )

    if cmd is CommandName.DOCTOR:
        steps = (
            ExecutionStep(
                name="detect-gis",
                runtime=RuntimeKind.PLAIN_PYTHON,
                **_tool_meta(root, "doctor"),
                script=str(common / "detect_gis.py"),
                arguments=("--json",),
            ),
        )
    elif cmd is CommandName.INSPECT:
        args = ["--root", request.input_root or ""]
        reports: list[str] = []
        if request.output_root:
            report = _join_user_path(request.output_root, "input_manifest.json")
            args += ["--output", report]
            reports.append(report)
        steps = (
            ExecutionStep(
                name="inspect-inputs",
                runtime=RuntimeKind.PLAIN_PYTHON,
                **_tool_meta(root, "inspect"),
                script=str(common / "inspect_inputs.py"),
                arguments=tuple(args),
                reports=tuple(reports),
            ),
        )
    elif cmd is CommandName.SEGMENT:
        steps = (
            ExecutionStep(
                name="segment-preliminary",
                runtime=RuntimeKind.PLAIN_PYTHON,
                **_tool_meta(root, "segment"),
                script=str(common / "segment_preliminary.py"),
                arguments=("--config", request.config or ""),
            ),
        )
    elif cmd is CommandName.BUILD_DATA:
        steps = (
            ExecutionStep(
                name="prepare-project-data",
                runtime=RuntimeKind.ARCGIS_PROPY,
                **_tool_meta(root, "build-data"),
                script=str(pro / "prepare_project_data.py"),
                arguments=("--config", request.config or ""),
                reports=("terrain_statistics_report.json",),
            ),
        )
    elif cmd is CommandName.VALIDATE:
        output = request.output_root or request.input_root or ""
        quality = _join_user_path(output, "quality_report.json")
        topology = _join_user_path(output, "topology_report.json")
        gpkg = request.gpkg or _join_user_path(
            request.input_root or "", "forest_compartments.gpkg"
        )
        steps = (
            ExecutionStep(
                name="validate-project",
                runtime=RuntimeKind.PLAIN_PYTHON,
                **_tool_meta(root, "validate-project"),
                script=str(common / "validate_project.py"),
                arguments=("--project", request.input_root or "", "--report", quality),
                accepted_exit_codes=(ExitCode.SUCCESS, ExitCode.VALIDATION_ISSUES),
                reports=(quality,),
            ),
            ExecutionStep(
                name="validate-topology",
                runtime=RuntimeKind.PLAIN_PYTHON,
                **_tool_meta(root, "validate-topology"),
                script=str(common / "validate_topology.py"),
                arguments=(
                    "--gpkg", gpkg,
                    "--layer", "xiaoban_preliminary",
                    "--report", topology,
                ),
                accepted_exit_codes=(ExitCode.SUCCESS, ExitCode.VALIDATION_ISSUES),
                reports=(topology,),
            ),
        )
    elif cmd is CommandName.PACKAGE:
        steps = (
            ExecutionStep(
                name="package-project",
                runtime=RuntimeKind.PLAIN_PYTHON,
                **_tool_meta(root, "package"),
                script=str(common / "package_project.py"),
                arguments=(
                    "--project", request.input_root or "",
                    "--output", request.zip_output or "",
                ),
            ),
        )
    elif cmd is CommandName.PREPARE_PRACTICE:
        args = [
            "--input-root", request.input_root or "",
            "--output-root", request.output_root or "",
        ]
        if request.config:
            args += ["--config", request.config]
        if request.propy_bat:
            args += ["--propy-bat", request.propy_bat]
        steps = (
            ExecutionStep(
                name="prepare-practice",
                runtime=RuntimeKind.CONTROL_ONLY,
                tool_id="prepare-practice", risk_level="medium", mutates_data=True, idempotent=False,
                script=str(common / "prepare_practice.py"),
                arguments=tuple(args),
                reports=(
                    _join_user_path(request.output_root or "", "00_Workflow/workflow_state.json"),
                ),
            ),
        )
    else:  # pragma: no cover - CommandName 已封闭
        raise AssertionError(f"unhandled command: {cmd}")

    return ExecutionPlan(
        command=cmd,
        platform=request.platform,
        steps=steps,
        metadata={
            "python_exe": request.python_exe,
            "propy_bat": request.propy_bat,
            "request_metadata": request.metadata,
            "tool_registry": "registry/tool_registry.json",
        },
    )
