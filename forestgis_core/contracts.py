"""统一命令、退出码和结果协议。

该模块只使用 Python 标准库，不依赖 ArcPy、GeoPandas 或任何平台 SDK。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any, Mapping


class ContractError(ValueError):
    """请求不符合统一契约。"""


class CommandName(str, Enum):
    DOCTOR = "doctor"
    INSPECT = "inspect"
    SEGMENT = "segment"
    BUILD_DATA = "build-data"
    VALIDATE = "validate"
    PACKAGE = "package"
    PROJECT = "project"
    PREPARE_PRACTICE = "prepare-practice"


class RuntimeKind(str, Enum):
    PLAIN_PYTHON = "plain-python"
    ARCGIS_PROPY = "arcgis-propy"
    CONTROL_ONLY = "control-only"


class ExitCode(IntEnum):
    SUCCESS = 0
    GENERAL_ERROR = 1
    VALIDATION_ISSUES = 2
    INPUT_ERROR = 3
    EXPERIMENTAL_FEATURE_DISABLED = 4
    ENVIRONMENT_ERROR = 5
    SCRIPT_ERROR = 6


_STATUS_BY_EXIT_CODE = {
    ExitCode.SUCCESS: "SUCCESS",
    ExitCode.GENERAL_ERROR: "ERROR",
    ExitCode.VALIDATION_ISSUES: "VALIDATION_ISSUES",
    ExitCode.INPUT_ERROR: "INPUT_ERROR",
    ExitCode.EXPERIMENTAL_FEATURE_DISABLED: "EXPERIMENTAL_FEATURE_DISABLED",
    ExitCode.ENVIRONMENT_ERROR: "ENVIRONMENT_ERROR",
    ExitCode.SCRIPT_ERROR: "SCRIPT_ERROR",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


_KEY_ALIASES = {
    "command": "command",
    "action": "command",
    "inputroot": "input_root",
    "inputdir": "input_root",
    "outputroot": "output_root",
    "outputdir": "output_root",
    "config": "config",
    "configpath": "config",
    "zipoutput": "zip_output",
    "zip": "zip_output",
    "gpkg": "gpkg",
    "pythonexe": "python_exe",
    "python": "python_exe",
    "propybat": "propy_bat",
    "propy": "propy_bat",
    "platform": "platform",
    "metadata": "metadata",
}


def _flatten_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    """展开常见平台包装层，但外层明确字段优先。"""
    result: dict[str, Any] = {}
    for wrapper in ("parameters", "arguments", "args", "options", "tool_input", "payload"):
        nested = payload.get(wrapper)
        if isinstance(nested, Mapping):
            result.update(nested)
    result.update({k: v for k, v in payload.items() if k not in {
        "parameters", "arguments", "args", "options", "tool_input", "payload"
    }})
    return result


@dataclass(frozen=True)
class CommandRequest:
    command: CommandName
    input_root: str | None = None
    output_root: str | None = None
    config: str | None = None
    zip_output: str | None = None
    gpkg: str | None = None
    python_exe: str | None = None
    propy_bat: str | None = None
    platform: str = "universal"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        platform: str | None = None,
    ) -> "CommandRequest":
        if not isinstance(payload, Mapping):
            raise ContractError("请求必须是 JSON 对象或字典")
        flat = _flatten_mapping(payload)
        normalized: dict[str, Any] = {}
        extras: dict[str, Any] = {}
        for key, value in flat.items():
            canonical = _KEY_ALIASES.get(_canonical_key(str(key)))
            if canonical:
                normalized[canonical] = value
            elif key not in {"schema_version", "request_id"}:
                extras[str(key)] = value

        raw_command = normalized.get("command")
        if raw_command is None:
            raise ContractError("缺少 command/action")
        try:
            command = CommandName(str(raw_command).strip().lower().replace("_", "-"))
        except ValueError as exc:
            allowed = ", ".join(c.value for c in CommandName)
            raise ContractError(f"不支持的命令: {raw_command}；允许: {allowed}") from exc

        metadata = normalized.get("metadata")
        if metadata is None:
            metadata = {}
        elif not isinstance(metadata, Mapping):
            raise ContractError("metadata 必须是对象")
        metadata = dict(metadata)
        # 保留通用请求追踪字段，同时不让它们污染核心参数。
        for trace_key in ("request_id", "schema_version"):
            if trace_key in flat and trace_key not in metadata:
                metadata[trace_key] = flat[trace_key]
        metadata.update(extras)

        request = cls(
            command=command,
            input_root=_optional_text(normalized.get("input_root")),
            output_root=_optional_text(normalized.get("output_root")),
            config=_optional_text(normalized.get("config")),
            zip_output=_optional_text(normalized.get("zip_output")),
            gpkg=_optional_text(normalized.get("gpkg")),
            python_exe=_optional_text(normalized.get("python_exe")),
            propy_bat=_optional_text(normalized.get("propy_bat")),
            platform=str(platform or normalized.get("platform") or "universal"),
            metadata=metadata,
        )
        request.validate()
        return request

    def validate(self) -> None:
        required: dict[CommandName, tuple[str, ...]] = {
            CommandName.INSPECT: ("input_root",),
            CommandName.SEGMENT: ("config",),
            CommandName.BUILD_DATA: ("config",),
            CommandName.VALIDATE: ("input_root",),
            CommandName.PACKAGE: ("input_root", "zip_output"),
            CommandName.PREPARE_PRACTICE: ("input_root", "output_root"),
        }
        missing = [name for name in required.get(self.command, ()) if not getattr(self, name)]
        if missing:
            raise ContractError(
                f"命令 {self.command.value} 缺少必需参数: {', '.join(missing)}"
            )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["command"] = self.command.value
        return data


@dataclass
class CommandResult:
    command: CommandName
    process_exit_code: int
    status: str | None = None
    platform: str = "universal"
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    reports: list[str] = field(default_factory=list)
    data_modified: bool | None = None
    original_inputs_modified: bool | None = None

    def __post_init__(self) -> None:
        if self.status is None:
            try:
                self.status = _STATUS_BY_EXIT_CODE[ExitCode(self.process_exit_code)]
            except (ValueError, KeyError):
                self.status = "ERROR" if self.process_exit_code else "SUCCESS"

    @property
    def ok(self) -> bool:
        return self.process_exit_code == ExitCode.SUCCESS

    def finish(self) -> "CommandResult":
        self.finished_at = utc_now()
        return self

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["command"] = self.command.value
        data["ok"] = self.ok
        return data


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
