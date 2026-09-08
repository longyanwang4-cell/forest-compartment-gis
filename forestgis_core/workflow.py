"""森林经理学实习 GIS 一键准备工作流。

仅负责编排现有稳定脚本，不在此重写分割、ArcPy 或拓扑算法。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .contracts import ExitCode, utc_now
from .error_memory import append_error_memory
from .policy import apply_execution_mode, requires_candidate_review
from .path_safety import PathSafetyError, assert_no_link_components, ensure_disjoint_roots, ensure_output_outside_input


class WorkflowError(RuntimeError):
    def __init__(self, message: str, exit_code: int = int(ExitCode.GENERAL_ERROR)):
        super().__init__(message)
        self.exit_code = int(exit_code)


@dataclass
class StepResult:
    step: str
    status: str
    exit_code: int
    started_at: str
    finished_at: str
    command: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    reports: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    recommended_next_action: str = "continue"
    attempt: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "reports": self.reports,
            "warnings": self.warnings,
            "errors": self.errors,
            "recommended_next_action": self.recommended_next_action,
            "attempt": self.attempt,
        }


@dataclass
class WorkflowPaths:
    root: Path
    workflow_dir: Path
    steps_dir: Path
    segment_dir: Path
    project_dir: Path
    reports_dir: Path
    package_dir: Path
    checkpoints_dir: Path
    state_file: Path
    summary_file: Path
    manifest_file: Path
    segment_config: Path
    build_config: Path
    normalized_existing_gpkg: Path
    decision_trace_file: Path
    error_memory_file: Path
    execution_plan_file: Path
    provenance_file: Path
    field_kit_dir: Path
    student_report_file: Path
    normalized_config_file: Path
    tool_registry_snapshot_file: Path

    @classmethod
    def from_root(cls, root: Path) -> "WorkflowPaths":
        workflow_dir = root / "00_Workflow"
        return cls(
            root=root,
            workflow_dir=workflow_dir,
            steps_dir=workflow_dir / "steps",
            segment_dir=root / "01_Segmentation",
            project_dir=root / "02_ProjectData",
            reports_dir=root / "03_Reports",
            package_dir=root / "04_Package",
            checkpoints_dir=workflow_dir / "checkpoints",
            state_file=workflow_dir / "workflow_state.json",
            summary_file=workflow_dir / "workflow_summary.json",
            manifest_file=workflow_dir / "input_manifest.json",
            segment_config=workflow_dir / "segment_config.generated.json",
            build_config=workflow_dir / "build_config.generated.json",
            normalized_existing_gpkg=workflow_dir / "existing_compartments_normalized.gpkg",
            decision_trace_file=workflow_dir / "decision_trace.jsonl",
            error_memory_file=workflow_dir / "error_memory.jsonl",
            execution_plan_file=workflow_dir / "execution_plan.json",
            provenance_file=root / "03_Reports" / "provenance.json",
            field_kit_dir=root / "03_Reports" / "Field_Kit",
            student_report_file=root / "03_Reports" / "学生工作流报告.html",
            normalized_config_file=workflow_dir / "normalized_config.json",
            tool_registry_snapshot_file=workflow_dir / "tool_registry_snapshot.json",
        )


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[bytes]]


def _default_command_runner(command: list[str], timeout_seconds: int | None = None) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        return subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            timeout=timeout_seconds if timeout_seconds and timeout_seconds > 0 else None,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        if isinstance(stdout, str):
            stdout = stdout.encode("utf-8", errors="replace")
        if isinstance(stderr, str):
            stderr = stderr.encode("utf-8", errors="replace")
        message = f"步骤运行超过超时限制 {timeout_seconds} 秒，已终止".encode("utf-8")
        return subprocess.CompletedProcess(command, int(ExitCode.SCRIPT_ERROR), stdout=stdout, stderr=stderr + b"\n" + message)


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    for enc in ("utf-8", "gb18030", "cp936"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise WorkflowError(f"JSON 根节点不是对象: {path}", ExitCode.INPUT_ERROR)
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _config_fingerprint(config: dict[str, Any]) -> str:
    # 人工审批标记是恢复时允许变化的控制字段，不属于业务配置。
    stable = json.loads(json.dumps(config, ensure_ascii=False))
    stable.pop("candidate_review_approved", None)
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _status_for_exit(code: int) -> str:
    if code == 0:
        return "SUCCESS"
    if code == 2:
        return "VALIDATION_ISSUES"
    return "FAILED"


def _candidate_files(manifest: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [x for x in manifest.get("files", []) if x.get("kind") == kind]


def _resolve_override(value: str | None, input_root: Path) -> str | None:
    if not value:
        return None
    p = Path(value)
    if not p.is_absolute():
        p = input_root / p
    try:
        assert_no_link_components(p)
    except PathSafetyError as exc:
        raise WorkflowError(str(exc), ExitCode.INPUT_ERROR) from exc
    if not p.exists() or not p.is_file():
        raise WorkflowError(f"显式输入不存在或不是普通文件: {p}", ExitCode.INPUT_ERROR)
    return str(p.resolve())


def select_input(
    manifest: dict[str, Any],
    kind: str,
    *,
    input_root: Path,
    override: str | None = None,
    required: bool = True,
) -> str | None:
    explicit = _resolve_override(override, input_root)
    if explicit:
        return explicit
    candidates = _candidate_files(manifest, kind)
    if not candidates:
        if required:
            raise WorkflowError(f"未识别到必需输入: {kind}", ExitCode.INPUT_ERROR)
        return None
    if len(candidates) > 1:
        paths = [str(x.get("relative_path") or x.get("path")) for x in candidates]
        raise WorkflowError(
            f"识别到多个 {kind}，为避免误选已暂停。请在工作流配置 input.{kind} 中明确指定：{paths}",
            ExitCode.INPUT_ERROR,
        )
    return str(Path(candidates[0]["path"]).resolve())


def _ensure_new_or_resume(paths: WorkflowPaths, resume: bool) -> dict[str, Any] | None:
    if paths.state_file.exists():
        if not resume:
            raise WorkflowError(
                f"输出目录已有工作流状态，请使用 -Resume 继续，或选择新的输出目录: {paths.root}",
                ExitCode.INPUT_ERROR,
            )
        return _read_json(paths.state_file)
    if paths.root.exists() and any(paths.root.iterdir()):
        raise WorkflowError(
            f"输出目录非空且没有可恢复状态，为防覆盖已停止: {paths.root}",
            ExitCode.INPUT_ERROR,
        )
    paths.root.mkdir(parents=True, exist_ok=True)
    return None


def _normalize_existing_compartments(
    source: str,
    target: Path,
    working_crs: str,
    prefix: str,
    start: int,
) -> tuple[str, int]:
    import geopandas as gpd
    from shapely.validation import make_valid

    gdf = gpd.read_file(source)
    if gdf.empty:
        raise WorkflowError("已有小班为空", ExitCode.INPUT_ERROR)
    if gdf.crs is None:
        raise WorkflowError("已有小班缺少坐标系", ExitCode.INPUT_ERROR)
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.apply(make_valid)
    gdf = gdf[~gdf.geometry.is_empty].copy()
    if working_crs and working_crs != "auto_utm":
        gdf = gdf.to_crs(working_crs)
    elif working_crs == "auto_utm":
        gdf = gdf.to_crs(gdf.estimate_utm_crs())
    if "XB_ID" not in gdf.columns:
        gdf["XB_ID"] = [f"{prefix}{i:02d}" for i in range(start, start + len(gdf))]
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    gdf.to_file(target, layer="xiaoban_preliminary", driver="GPKG")
    return str(target), int(len(gdf))


class PracticeWorkflow:
    def __init__(
        self,
        *,
        skill_root: Path,
        config: dict[str, Any],
        propy_bat: str,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.skill_root = skill_root.resolve()
        self.config = apply_execution_mode(config, config.get("execution_mode"))
        try:
            input_root, output_root = ensure_disjoint_roots(
                self.config["input_root"], self.config["output_root"]
            )
        except PathSafetyError as exc:
            raise WorkflowError(str(exc), ExitCode.INPUT_ERROR) from exc
        self.input_root = input_root
        self.paths = WorkflowPaths.from_root(output_root)
        self.propy_bat = str(Path(propy_bat).resolve())
        raw_timeout = self.config.get("step_timeout_seconds", 7200)
        try:
            self.step_timeout_seconds = int(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise WorkflowError("step_timeout_seconds必须为非负整数", ExitCode.INPUT_ERROR) from exc
        if self.step_timeout_seconds < 0:
            raise WorkflowError("step_timeout_seconds不能为负数", ExitCode.INPUT_ERROR)
        self.command_runner = command_runner or (
            lambda command: _default_command_runner(command, self.step_timeout_seconds)
        )
        self.state: dict[str, Any] = {}
        self.accumulated_issues: list[dict[str, Any]] = []
        self.attempt = 1

    def _trace(self, event: str, **payload: Any) -> None:
        record = {"timestamp": utc_now(), "event": event, "attempt": self.attempt, **payload}
        self.paths.decision_trace_file.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.decision_trace_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _write_execution_plan(self) -> None:
        existing_hint = bool(((self.config.get("input") or {}).get("compartments")))
        steps = [
            {"id": "doctor", "conditional": False, "risk": "low"},
            {"id": "inspect", "conditional": False, "risk": "low"},
            {"id": "normalize-existing-compartments", "conditional": "if existing compartments", "risk": "medium"},
            {"id": "segment", "conditional": "if no existing compartments", "risk": "medium", "human_review": "strict mode before build"},
            {"id": "build-data", "conditional": False, "risk": "medium"},
            {"id": "field-kit", "conditional": "reporting.field_kit", "risk": "low"},
            {"id": "validate-gdb", "conditional": False, "risk": "low"},
            {"id": "validate-project", "conditional": False, "risk": "low"},
            {"id": "validate-topology", "conditional": False, "risk": "low"},
            {"id": "provenance", "conditional": False, "risk": "low"},
            {"id": "student-report", "conditional": "reporting.html_summary", "risk": "low"},
            {"id": "package", "conditional": "package.enabled", "risk": "low"},
        ]
        payload = {
            "schema_version": "1.0",
            "workflow": "prepare-practice",
            "execution_mode": self.config.get("execution_mode", "standard"),
            "input_root": str(self.input_root),
            "output_root": str(self.paths.root),
            "existing_compartments_explicitly_configured": existing_hint,
            "safety": {"original_inputs_read_only": True, "automatic_aprx_creation": "disabled"},
            "steps": steps,
        }
        _write_json(self.paths.execution_plan_file, payload)

    def _save_state(self) -> None:
        self.state["updated_at"] = utc_now()
        _write_json(self.paths.state_file, self.state)

    def _snapshot_state(self, reason: str) -> None:
        """保存轻量状态快照，便于暂停后恢复和追踪多次验证。"""
        self.paths.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{time.time_ns() % 1_000_000_000:09d}"
        target = self.paths.checkpoints_dir / f"{stamp}_{reason}.json"
        payload = dict(self.state)
        payload["snapshot_reason"] = reason
        _write_json(target, payload)

    def _reset_steps(self, names: Iterable[str]) -> None:
        completed = self.state.setdefault("completed_steps", [])
        review = self.state.setdefault("review_steps", [])
        for name in names:
            while name in completed:
                completed.remove(name)
            while name in review:
                review.remove(name)

    def _write_summary(self, status: str, *, issues: list[dict[str, Any]] | None = None) -> None:
        self.paths.reports_dir.mkdir(parents=True, exist_ok=True)
        manual_src = self.skill_root / "docs" / "ArcGISPro_手动创建小班项目.md"
        manual_dst = self.paths.reports_dir / "ArcGISPro_手动创建小班项目.md"
        if manual_src.exists():
            shutil.copy2(manual_src, manual_dst)
        summary = {
            "status": status,
            "input_root": str(self.input_root),
            "output_root": str(self.paths.root),
            "project_data": str(self.paths.project_dir),
            "reports": str(self.paths.reports_dir),
            "workflow_state": str(self.paths.state_file),
            "manual_arcgis_guide": str(manual_dst if manual_dst.exists() else manual_src),
            "original_inputs_modified": False,
            "attempt": self.attempt,
            "execution_mode": self.config.get("execution_mode", "standard"),
            "decision_trace": str(self.paths.decision_trace_file),
            "provenance": str(self.paths.provenance_file),
            "field_kit": str(self.paths.field_kit_dir),
            "student_html_report": str(self.paths.student_report_file),
            "issues": issues or [],
        }
        _write_json(self.paths.summary_file, summary)
        lines = [
            "森林经理学实习 GIS 工作流结果",
            f"状态: {status}",
            f"输出目录: {self.paths.root}",
            f"项目数据: {self.paths.project_dir}",
            f"检查报告: {self.paths.reports_dir}",
        ]
        if issues:
            lines.append("需要核查的问题:")
            lines.extend(f"- {x.get('code', 'UNKNOWN')} ({x.get('severity', 'unknown')})" for x in issues)
            lines.append("修正后请使用同一命令加 -Resume（或 -Revalidate）重新检查。")
        else:
            lines.append("下一步: 按 ArcGISPro_手动创建小班项目.md 新建或打开 ArcGIS Pro 项目。")
        (self.paths.reports_dir / "学生结果摘要.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _step_path(self, name: str) -> Path:
        return self.paths.steps_dir / f"{name}.json"

    def _is_completed(self, name: str) -> bool:
        return name in self.state.get("completed_steps", []) and self._step_path(name).exists()

    def _run_command(
        self,
        name: str,
        command: list[str],
        *,
        accepted: Iterable[int] = (0,),
        complete_on: Iterable[int] = (0,),
        reports: Iterable[Path] = (),
    ) -> StepResult:
        started = utc_now()
        self._trace("step_start", step=name, command=[str(x) for x in command])
        cp = self.command_runner(command)
        code = int(cp.returncode)
        result = StepResult(
            step=name,
            status=_status_for_exit(code),
            exit_code=code,
            started_at=started,
            finished_at=utc_now(),
            command=[str(x) for x in command],
            stdout=_decode(cp.stdout),
            stderr=_decode(cp.stderr),
            reports=[str(p) for p in reports if p.exists()],
            attempt=self.attempt,
        )
        if code not in set(int(x) for x in accepted):
            result.errors.append(f"步骤 {name} 失败，exit={code}")
            result.recommended_next_action = "stop"
            memory = append_error_memory(
                self.paths.error_memory_file, step=name, exit_code=code,
                text=(result.stderr or result.stdout or result.errors[-1]),
                rules_path=self.skill_root / "references" / "error_memory_rules.json",
            )
            result.errors.append(f"错误分类: {memory.get('code')}；建议: {memory.get('suggestion')}")
        elif code == 2:
            result.warnings.append("检查完成，但发现需要人工核查的问题")
            result.recommended_next_action = "pause_for_review"
        _write_json(self._step_path(name), result.to_dict())
        self._trace("step_finish", step=name, exit_code=code, status=result.status, recommended_next_action=result.recommended_next_action)
        accepted_codes = set(int(x) for x in accepted)
        complete_codes = set(int(x) for x in complete_on)
        completed = self.state.setdefault("completed_steps", [])
        review = self.state.setdefault("review_steps", [])
        if code in complete_codes:
            if name not in completed:
                completed.append(name)
            while name in review:
                review.remove(name)
        elif code in accepted_codes:
            while name in completed:
                completed.remove(name)
            if name not in review:
                review.append(name)
        self.state["current_step"] = name
        self._save_state()
        if code not in set(int(x) for x in accepted):
            raise WorkflowError(result.errors[-1], code or ExitCode.SCRIPT_ERROR)
        return result

    def _python(self, script: Path, *args: str) -> list[str]:
        return [sys.executable, str(script), *map(str, args)]

    def _propy(self, script: Path, *args: str) -> list[str]:
        if os.name == "nt":
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", "call", self.propy_bat, str(script), *map(str, args)]
        return [self.propy_bat, str(script), *map(str, args)]

    def _record_internal_step(self, name: str, payload: dict[str, Any]) -> None:
        now = utc_now()
        result = StepResult(
            step=name,
            status="SUCCESS",
            exit_code=0,
            started_at=now,
            finished_at=now,
            reports=[str(x) for x in payload.get("reports", [])],
            stdout=json.dumps(payload, ensure_ascii=False, indent=2),
            attempt=self.attempt,
        )
        _write_json(self._step_path(name), result.to_dict())
        completed = self.state.setdefault("completed_steps", [])
        if name not in completed:
            completed.append(name)
        self.state["current_step"] = name
        self._save_state()

    def preview(self) -> dict[str, Any]:
        """Write and return a read-only execution plan without calling GIS tools."""
        self.paths.workflow_dir.mkdir(parents=True, exist_ok=True)
        self._write_execution_plan()
        _write_json(self.paths.normalized_config_file, self.config)
        registry_src = self.skill_root / "registry" / "tool_registry.json"
        if registry_src.exists():
            shutil.copy2(registry_src, self.paths.tool_registry_snapshot_file)
        plan = _read_json(self.paths.execution_plan_file)
        self._trace("dry_run_plan", execution_mode=self.config.get("execution_mode"))
        return plan

    def run(self, *, resume: bool = False, revalidate: bool = False) -> int:
        prior = _ensure_new_or_resume(self.paths, resume)
        fingerprint = _config_fingerprint(self.config)
        if prior:
            if prior.get("config_fingerprint") != fingerprint:
                raise WorkflowError("恢复配置与原工作流不一致，已停止", ExitCode.INPUT_ERROR)
            self.state = prior
            self.attempt = int(self.state.get("resume_count", 0)) + 2
            self._snapshot_state("before_resume")
            self.state["resume_count"] = int(self.state.get("resume_count", 0)) + 1
            self.state["status"] = "RUNNING"
            self.state.pop("issues", None)
            self.state.pop("recommended_next_action", None)
            # v1.3.0曾把exit=2的验证步骤记为完成。恢复暂停任务时强制重验，兼容旧状态。
            if prior.get("status") == "PAUSED_FOR_REVIEW" or revalidate:
                self._reset_steps(("validate-gdb", "validate-project", "validate-topology", "provenance", "student-report", "package"))
        else:
            self.paths.steps_dir.mkdir(parents=True, exist_ok=True)
            self.paths.reports_dir.mkdir(parents=True, exist_ok=True)
            self.paths.package_dir.mkdir(parents=True, exist_ok=True)
            self.state = {
                "schema_version": "1.2",
                "workflow": "prepare-practice",
                "execution_mode": self.config.get("execution_mode", "standard"),
                "status": "RUNNING",
                "started_at": utc_now(),
                "updated_at": utc_now(),
                "input_root": str(self.input_root),
                "output_root": str(self.paths.root),
                "config_fingerprint": fingerprint,
                "completed_steps": [],
                "review_steps": [],
                "resume_count": 0,
                "current_step": None,
            }
            self._save_state()

        self._write_execution_plan()
        _write_json(self.paths.normalized_config_file, self.config)
        registry_src = self.skill_root / "registry" / "tool_registry.json"
        if registry_src.exists():
            shutil.copy2(registry_src, self.paths.tool_registry_snapshot_file)
        self._trace("workflow_start_or_resume", status=self.state.get("status"), execution_mode=self.config.get("execution_mode"))

        common = self.skill_root / "scripts" / "common"
        pro = self.skill_root / "scripts" / "arcgis_pro"

        if not self._is_completed("doctor"):
            self._run_command("doctor", self._python(common / "detect_gis.py", "--json"))

        if not self._is_completed("inspect"):
            self.paths.workflow_dir.mkdir(parents=True, exist_ok=True)
            self._run_command(
                "inspect",
                self._python(common / "inspect_inputs.py", "--root", str(self.input_root), "--output", str(self.paths.manifest_file)),
                reports=(self.paths.manifest_file,),
            )
        manifest = _read_json(self.paths.manifest_file)
        overrides = self.config.get("input", {}) or {}
        imagery = select_input(manifest, "imagery", input_root=self.input_root, override=overrides.get("imagery"), required=True)
        boundary = select_input(manifest, "boundary", input_root=self.input_root, override=overrides.get("boundary"), required=True)
        dem = select_input(manifest, "dem", input_root=self.input_root, override=overrides.get("dem"), required=False)

        existing = _resolve_override(overrides.get("compartments"), self.input_root)
        if not existing:
            compartments = _candidate_files(manifest, "compartment")
            if len(compartments) > 1:
                raise WorkflowError("识别到多个已有小班，请在配置 input.compartments 中明确指定", ExitCode.INPUT_ERROR)
            existing = str(Path(compartments[0]["path"]).resolve()) if compartments else None

        working_crs = str(self.config.get("working_crs") or "auto_utm")
        naming = self.config.get("naming", {}) or {}
        prefix = str(naming.get("prefix") or "XB")
        start = int(naming.get("start") or 1)

        if existing:
            if not self._is_completed("normalize-existing-compartments"):
                normalized, actual_count = _normalize_existing_compartments(
                    existing, self.paths.normalized_existing_gpkg, working_crs, prefix, start
                )
                self._record_internal_step(
                    "normalize-existing-compartments",
                    {"source": existing, "normalized": normalized, "compartment_count": actual_count, "reports": [self.paths.normalized_existing_gpkg]},
                )
            normalized_gpkg = str(self.paths.normalized_existing_gpkg)
            import geopandas as gpd
            actual_count = int(len(gpd.read_file(normalized_gpkg, layer="xiaoban_preliminary")))
            preliminary = existing
            topology_gpkg = normalized_gpkg
            expected_count = actual_count
        else:
            expected_count = self.config.get("expected_compartment_count")
            if expected_count is None:
                raise WorkflowError(
                    "未发现已有小班，必须在工作流配置中明确 expected_compartment_count（本次实习可填写20）",
                    ExitCode.INPUT_ERROR,
                )
            expected_count = int(expected_count)
            if expected_count <= 0:
                raise WorkflowError("expected_compartment_count 必须大于0", ExitCode.INPUT_ERROR)
            seg_cfg = {
                "input": {"imagery": imagery, "boundary": boundary, "dem": dem},
                "output_dir": str(self.paths.segment_dir),
                "working_crs": working_crs,
                "segmentation": {
                    "candidate_compartments": expected_count,
                    "superpixels": int((self.config.get("segmentation") or {}).get("superpixels", 650)),
                    "compactness": float((self.config.get("segmentation") or {}).get("compactness", 8.0)),
                    "max_pixels": int((self.config.get("segmentation") or {}).get("max_pixels", 50_000_000)),
                },
                "naming": {"prefix": prefix, "start": start},
            }
            _write_json(self.paths.segment_config, seg_cfg)
            if not self._is_completed("segment"):
                if self.paths.segment_dir.exists() and any(self.paths.segment_dir.iterdir()):
                    raise WorkflowError("候选分割目录非空且步骤未完成，请人工检查后换新输出目录", ExitCode.INPUT_ERROR)
                self._run_command(
                    "segment",
                    self._python(common / "segment_preliminary.py", "--config", str(self.paths.segment_config)),
                    reports=(self.paths.segment_dir / "segmentation_report.json",),
                )
            seg_report = _read_json(self.paths.segment_dir / "segmentation_report.json")
            if int(seg_report.get("candidate_compartments", -1)) != expected_count:
                self.accumulated_issues.append({"code": "SEGMENT_COUNT_MISMATCH", "severity": "high", "details": seg_report})
            preliminary = str(self.paths.segment_dir / "shapefile" / "xiaoban_preliminary.shp")
            topology_gpkg = str(self.paths.segment_dir / "forest_compartments.gpkg")

            if requires_candidate_review(self.config) and not bool(self.config.get("candidate_review_approved", False)):
                issue = {
                    "code": "CANDIDATE_SEGMENT_REVIEW_REQUIRED",
                    "severity": "medium",
                    "message": "严格模式要求在构建GDB前人工检查候选小班。确认后使用同一配置设置candidate_review_approved=true并-Resume。",
                    "candidate": preliminary,
                }
                self.state["status"] = "PAUSED_FOR_REVIEW"
                self.state["issues"] = [issue]
                self.state["recommended_next_action"] = "review_candidate_then_resume"
                self._save_state(); self._write_summary("PAUSED_FOR_REVIEW", issues=[issue])
                if bool((self.config.get("reporting") or {}).get("html_summary", True)):
                    self._run_command("student-report", self._python(common / "render_student_report.py", "--workflow-root", str(self.paths.root), "--output", str(self.paths.student_report_file)), reports=(self.paths.student_report_file,))
                self._snapshot_state("candidate_review")
                self._trace("human_review_gate", gate="candidate_segmentation", decision="pause")
                return int(ExitCode.VALIDATION_ISSUES)

        terrain = self.config.get("terrain", {}) or {}
        if dem:
            if terrain.get("dem_z_unit") in (None, ""):
                raise WorkflowError("检测到DEM，配置必须明确 terrain.dem_z_unit", ExitCode.INPUT_ERROR)
            if terrain.get("z_factor") is None:
                raise WorkflowError("检测到DEM，配置必须明确 terrain.z_factor", ExitCode.INPUT_ERROR)

        build_cfg: dict[str, Any] = {
            "input": {"imagery": imagery, "boundary": boundary, "dem": dem},
            "preliminary_compartments": preliminary,
            "output_dir": str(self.paths.project_dir),
            "working_crs": working_crs,
            "allow_existing_output": False,
            "expected_compartment_count": expected_count,
        }
        if dem:
            build_cfg["terrain"] = {
                "dem_z_unit": terrain.get("dem_z_unit"),
                "z_factor": terrain.get("z_factor"),
                "dem_cell_size": terrain.get("dem_cell_size"),
            }
        _write_json(self.paths.build_config, build_cfg)

        if not self._is_completed("build-data"):
            if self.paths.project_dir.exists() and any(self.paths.project_dir.iterdir()):
                raise WorkflowError("项目数据目录非空且build-data未完成，为防覆盖已停止", ExitCode.INPUT_ERROR)
            self._run_command(
                "build-data",
                self._propy(pro / "prepare_project_data.py", "--config", str(self.paths.build_config)),
                reports=(self.paths.project_dir / "terrain_statistics_report.json",),
            )

        reporting_cfg = self.config.get("reporting", {}) or {}
        if bool(reporting_cfg.get("field_kit", True)) and not self._is_completed("field-kit"):
            self._run_command(
                "field-kit",
                self._python(common / "generate_field_kit.py", "--output", str(self.paths.field_kit_dir)),
                reports=(self.paths.field_kit_dir / "field_form_schema.json",),
            )

        terrain_report = self.paths.project_dir / "terrain_statistics_report.json"
        if terrain_report.exists():
            tr = _read_json(terrain_report)
            checks = tr.get("checks", {}) or {}
            for key in ("stats_tables_written", "elev_within_dem_range", "slope_within_0_90", "inputs_unchanged"):
                if checks.get(key) is False:
                    self.accumulated_issues.append({"code": f"TERRAIN_{key.upper()}", "severity": "high"})
            if checks.get("count_matches_expected") is False:
                self.accumulated_issues.append({"code": "COMPARTMENT_COUNT_MISMATCH", "severity": "high"})
            if int(checks.get("null_count") or 0) > 0:
                self.accumulated_issues.append({"code": "DEM_NO_DATA", "severity": "medium", "count": checks.get("null_count")})

        validation = self.config.get("validation", {}) or {}
        if not self._is_completed("validate-gdb"):
            gdb_quality = self.paths.reports_dir / "gdb_quality_report.json"
            args = [
                "--project", str(self.paths.project_dir),
                "--report", str(gdb_quality),
                "--expected-count", str(expected_count),
                "--overlap-tolerance-m2", str(float(validation.get("overlap_tolerance_m2", 1.0))),
                "--gap-tolerance-m2", str(float(validation.get("gap_tolerance_m2", 5.0))),
                "--outside-tolerance-m2", str(float(validation.get("outside_tolerance_m2", 1.0))),
                "--min-coverage-ratio", str(float(validation.get("min_coverage_ratio", 0.999))),
            ]
            if dem:
                args.append("--require-terrain")
            if bool(validation.get("require_projected_crs", True)):
                args.append("--require-projected-crs")
            if bool(validation.get("require_meter_unit", True)):
                args.append("--require-meter-unit")
            self._run_command(
                "validate-gdb",
                self._propy(pro / "validate_project_gdb.py", *args),
                accepted=(0, 2),
                complete_on=(0,),
                reports=(gdb_quality,),
            )

        if not self._is_completed("validate-project"):
            quality = self.paths.reports_dir / "quality_report.json"
            self._run_command(
                "validate-project",
                self._python(common / "validate_project.py", "--project", str(self.paths.project_dir), "--report", str(quality)),
                accepted=(0, 2),
                complete_on=(0,),
                reports=(quality,),
            )
        if not self._is_completed("validate-topology"):
            topology = self.paths.reports_dir / "topology_report.json"
            self._run_command(
                "validate-topology",
                self._python(common / "validate_topology.py", "--gpkg", topology_gpkg, "--layer", "xiaoban_preliminary", "--report", str(topology)),
                accepted=(0, 2),
                complete_on=(0,),
                reports=(topology,),
            )

        for step in ("validate-gdb", "validate-project", "validate-topology"):
            p = self._step_path(step)
            if p.exists() and int(_read_json(p).get("exit_code", 0)) == 2:
                self.accumulated_issues.append({"code": step.upper().replace("-", "_"), "severity": "high"})

        if not self._is_completed("provenance"):
            hash_mode = str((self.config.get("provenance") or {}).get("hash_mode", "sampled"))
            version = (self.skill_root / "VERSION").read_text(encoding="utf-8").strip() if (self.skill_root / "VERSION").exists() else "unknown"
            self._run_command(
                "provenance",
                self._python(common / "generate_provenance.py", "--workflow-root", str(self.paths.root), "--input-root", str(self.input_root), "--output", str(self.paths.provenance_file), "--hash-mode", hash_mode, "--skill-version", version),
                reports=(self.paths.provenance_file,),
            )

        package_cfg = self.config.get("package", {}) or {}
        package_enabled = bool(package_cfg.get("enabled", True))
        if self.accumulated_issues:
            self.state["status"] = "PAUSED_FOR_REVIEW"
            self.state["issues"] = self.accumulated_issues
            self.state["recommended_next_action"] = "review_reports_then_resume"
            self.state["last_paused_at"] = utc_now()
            self._save_state()
            self._write_summary("PAUSED_FOR_REVIEW", issues=self.accumulated_issues)
            if bool((self.config.get("reporting") or {}).get("html_summary", True)):
                self._run_command("student-report", self._python(common / "render_student_report.py", "--workflow-root", str(self.paths.root), "--output", str(self.paths.student_report_file)), reports=(self.paths.student_report_file,))
            self._snapshot_state("paused_for_review")
            return int(ExitCode.VALIDATION_ISSUES)

        # 先生成交付摘要和手动建项目说明，再打包，确保ZIP内含报告与说明。
        self._write_summary("SUCCESS")
        if bool((self.config.get("reporting") or {}).get("html_summary", True)) and not self._is_completed("student-report"):
            self._run_command("student-report", self._python(common / "render_student_report.py", "--workflow-root", str(self.paths.root), "--output", str(self.paths.student_report_file)), reports=(self.paths.student_report_file,))

        if package_enabled and not self._is_completed("package"):
            zip_output = package_cfg.get("zip_output")
            zip_path = Path(zip_output).resolve() if zip_output else self.paths.package_dir / f"{self.paths.root.name}.zip"
            try:
                zip_path = ensure_output_outside_input(self.input_root, zip_path)
            except PathSafetyError as exc:
                raise WorkflowError(str(exc), ExitCode.INPUT_ERROR) from exc
            try:
                self._run_command(
                    "package",
                    self._python(common / "package_project.py", "--project", str(self.paths.root), "--output", str(zip_path), "--mode", "delivery"),
                    reports=(zip_path,),
                )
            except WorkflowError as exc:
                issue = {"code": "PACKAGE_FAILED", "severity": "high", "message": str(exc)}
                self.state["status"] = "FAILED"
                self.state["issues"] = [issue]
                self.state["recommended_next_action"] = "fix_package_error_then_resume"
                self._save_state()
                self._write_summary("PACKAGE_FAILED", issues=[issue])
                self._snapshot_state("package_failed")
                raise

        self.state["status"] = "SUCCESS"
        self.state["finished_at"] = utc_now()
        self.state["recommended_next_action"] = "manually_create_or_open_arcgis_pro_project"
        self._save_state()
        self._snapshot_state("success")
        self._trace("workflow_finish", status="SUCCESS")
        return int(ExitCode.SUCCESS)
