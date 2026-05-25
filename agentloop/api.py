"""JSON API and view-model builders for the AgentLoop local UI."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .config import RUNTIME_PRESETS, VALID_ROLES, detect_runtime_definitions
from .locks import LockHeld, lock_path, task_lock
from .logs import bounded_text, bounded_workspace_file, resolve_under
from .models import default_state
from .tasks import (
    current_task_id,
    effective_config,
    list_task_ids,
    load_task_config,
    load_task_state,
    save_task_config_patch,
    set_current_task_id,
    task_dir,
    task_state_path,
)
from .workspace import WorkspaceError, agentloop_path, config_path, load_config, save_state, write_json
from .transcripts import list_transcripts, load_transcript
from .workflow import (
    approve_task,
    cancel_task,
    run_task,
    start_research,
    start_task,
    submit_framing_answers,
)


ACTION_STATUSES_FOR_RUN = {"READY_TO_START", "IMPLEMENTING_AND_TESTING"}


ROLE_ORDER = ["framer", "investigator", "architect", "implementer", "tester", "reviewer", "integrator"]
HIDDEN_UI_RUNTIMES = {"example-agent"}

RESEARCH_RUNNING_STATUSES = {"INVESTIGATING", "DESIGNING"}


def _title_from_state(state: dict[str, Any], task_id: str) -> str:
    goal = state.get("goal") if isinstance(state.get("goal"), dict) else {}
    title = state.get("title") or goal.get("raw_request") or task_id
    return str(title).replace("\n", " ")[:120]


def _lock_error(root: Path, task_id: str) -> str | None:
    path = lock_path(root, task_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    pid = data.get("pid", "?") if isinstance(data, dict) else "?"
    started_at = data.get("started_at", "?") if isinstance(data, dict) else "?"
    return f"locked by pid {pid} since {started_at}"


def build_task_list(root: Path) -> dict[str, Any]:
    current = current_task_id(root)
    rows: list[dict[str, Any]] = []
    for task_id in list_task_ids(root):
        try:
            state = load_task_state(root, task_id)
            row = {
                "task_id": task_id,
                "title": _title_from_state(state, task_id),
                "status": state.get("status") or "UNKNOWN",
                "current_phase": state.get("current_phase"),
                "iteration": state.get("iteration", 0),
                "max_iterations": state.get("max_iterations") or effective_config(root, task_id).get("max_iterations"),
                "updated_at": state.get("updated_at") or state.get("created_at"),
                "current": task_id == current,
                "locked": _lock_error(root, task_id) is not None,
                "error": None,
            }
        except WorkspaceError as exc:
            row = {
                "task_id": task_id,
                "title": task_id,
                "status": "UNKNOWN",
                "current_phase": None,
                "iteration": None,
                "max_iterations": None,
                "updated_at": None,
                "current": task_id == current,
                "locked": _lock_error(root, task_id) is not None,
                "error": str(exc),
            }
        rows.append(row)
    rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {"current_task_id": current, "tasks": rows}


def _runtime_status(name: str, runtime: dict[str, Any], *, configured: bool, detected: bool) -> tuple[str, str]:
    adapter = runtime.get("adapter") or "command"
    command = runtime.get("command")
    if configured:
        if adapter == "manual":
            return "manual_fallback", "manual fallback; writes prompts and does not call a coding agent"
        if isinstance(command, str) and shutil.which(command):
            return "active", "configured and command is on PATH"
        if isinstance(command, str) and Path(command).exists():
            return "active", "configured and command path exists"
        return "configured_missing", "configured but command was not found"
    if detected:
        return "detected_not_injected", "detected on this machine but not injected into config"
    return "not_injected", "preset is available but not injected"


def _runtime_row(name: str, runtime: dict[str, Any], *, configured: bool, detected: bool) -> dict[str, Any]:
    runtime = runtime if isinstance(runtime, dict) else {}
    status, status_label = _runtime_status(name, runtime, configured=configured, detected=detected)
    return {
        "name": name,
        "adapter": runtime.get("adapter") or "command",
        "command": runtime.get("command"),
        "args": runtime.get("args") or [],
        "stdin_file": runtime.get("stdin_file"),
        "timeout_seconds": runtime.get("timeout_seconds"),
        "description": runtime.get("description"),
        "configured": configured,
        "detected": detected,
        "selectable": configured and status in {"active", "manual_fallback"},
        "status": status,
        "status_label": status_label,
    }


def runtime_catalog(config: dict[str, Any]) -> list[dict[str, Any]]:
    runtimes = config.get("runtimes", {}) if isinstance(config.get("runtimes"), dict) else {}
    detected = detect_runtime_definitions()
    names = set(RUNTIME_PRESETS) | set(detected) | set(runtimes)
    rows: list[dict[str, Any]] = []
    order = {"active": 0, "manual_fallback": 1, "configured_missing": 2, "detected_not_injected": 3, "not_injected": 4}
    for name in names:
        if name in HIDDEN_UI_RUNTIMES:
            continue
        configured = name in runtimes
        detected_here = name in detected
        runtime = runtimes.get(name) or detected.get(name) or RUNTIME_PRESETS.get(name) or {}
        rows.append(_runtime_row(name, runtime, configured=configured, detected=detected_here))
    rows.sort(key=lambda item: (order.get(str(item.get("status")), 99), str(item.get("name"))))
    return rows


def role_runtime_defaults(config: dict[str, Any]) -> list[dict[str, Any]]:
    runtimes = config.get("runtimes", {}) if isinstance(config.get("runtimes"), dict) else {}
    roles = config.get("roles", {}) if isinstance(config.get("roles"), dict) else {}
    default_runtime = config.get("default_runtime") or "manual"
    rows: list[dict[str, Any]] = []
    for role in ROLE_ORDER:
        role_cfg = roles.get(role, {}) if isinstance(roles.get(role, {}), dict) else {}
        runtime_name = role_cfg.get("runtime") or default_runtime
        rows.append(
            {
                "role": role,
                "runtime": runtime_name,
                "configured_runtime": role_cfg.get("runtime"),
                "uses_global_default": not bool(role_cfg.get("runtime")),
                "available": runtime_name in runtimes,
            }
        )
    return rows


def patch_settings(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WorkspaceError("Settings payload must be an object.")
    config = load_config(root)
    role_runtimes = payload.get("role_runtimes")
    if role_runtimes is not None:
        if not isinstance(role_runtimes, dict):
            raise WorkspaceError("role_runtimes must be an object mapping role -> runtime name.")
        runtimes = config.get("runtimes", {}) if isinstance(config.get("runtimes"), dict) else {}
        roles = config.setdefault("roles", {})
        if not isinstance(roles, dict):
            roles = {}
            config["roles"] = roles
        for role, runtime_name in role_runtimes.items():
            if role not in ROLE_ORDER:
                raise WorkspaceError(f"Unknown role: {role}")
            runtime_name = str(runtime_name or "").strip()
            if not runtime_name:
                raise WorkspaceError(f"Runtime for {role} cannot be empty.")
            if runtime_name not in runtimes:
                raise WorkspaceError(f"Runtime '{runtime_name}' is not configured.")
            role_cfg = roles.setdefault(role, {})
            if not isinstance(role_cfg, dict):
                role_cfg = {}
                roles[role] = role_cfg
            role_cfg["runtime"] = runtime_name
        write_json(config_path(root), config)
    return build_settings(root)


def build_settings(root: Path) -> dict[str, Any]:
    config = load_config(root)
    tasks = build_task_list(root)["tasks"]
    by_status: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status") or "UNKNOWN")
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "usage": {
            "task_count": len(tasks),
            "by_status": by_status,
            "current_task_id": current_task_id(root),
        },
        "runtime": {
            "default_runtime": config.get("default_runtime") or "manual",
            "runtimes": runtime_catalog(config),
            "role_defaults": role_runtime_defaults(config),
        },
    }


_PLACEHOLDER_ANSWERS = {"", "unanswered", "n/a", "na", "tbd", "none"}


def _blocking_count(questions: list[Any]) -> int:
    count = 0
    for item in questions:
        if not isinstance(item, dict):
            continue
        answer = str(item.get("answer") or "").strip().lower()
        if item.get("blocking") and answer in _PLACEHOLDER_ANSWERS:
            count += 1
    return count


def available_actions(state: dict[str, Any], lock_reason: str | None = None) -> dict[str, Any]:
    status = state.get("status")
    locked_reason = lock_reason or None

    def action(enabled: bool, reason: str | None = None) -> dict[str, Any]:
        if locked_reason and enabled:
            return {"enabled": False, "reason": locked_reason}
        return {"enabled": enabled, "reason": reason}

    questions = state.get("framing_questions") if isinstance(state.get("framing_questions"), list) else []
    blocking = _blocking_count(questions)

    submit_framing_enabled = status == "FRAMING_REVIEW"
    start_research_enabled = status == "FRAMING_REVIEW" and blocking == 0
    approve_enabled = status == "WAITING_FOR_ALIGNMENT"
    run_enabled = status in ACTION_STATUSES_FOR_RUN
    cancel_enabled = status not in {"CREATED", "DONE", "CANCELLED", "FRAMING"}

    start_research_reason: str | None = None
    if not start_research_enabled:
        if status != "FRAMING_REVIEW":
            start_research_reason = f"status is {status}"
        else:
            start_research_reason = f"{blocking} blocking question(s) unanswered"

    return {
        "approve": action(approve_enabled, None if approve_enabled else f"status is {status}"),
        "run": action(run_enabled, None if run_enabled else f"status is {status}"),
        "cancel": action(cancel_enabled, None if cancel_enabled else f"status is {status}"),
        "delete": action(True),
        "config": action(True),
        "submit_framing": action(submit_framing_enabled, None if submit_framing_enabled else f"status is {status}"),
        "start_research": action(start_research_enabled, start_research_reason),
    }


def build_framing_review(state: dict[str, Any]) -> dict[str, Any] | None:
    status = state.get("status")
    if status not in ("FRAMING_REVIEW", "FRAMING"):
        return None
    questions = state.get("framing_questions") if isinstance(state.get("framing_questions"), list) else []
    blocking = _blocking_count(questions)
    framing = state.get("framing") if isinstance(state.get("framing"), dict) else {}
    running = status == "FRAMING" or bool(state.get("framing_running"))
    return {
        "required": True,
        "meaning": "Answer the framer's open questions. When no blocking questions remain you can start research.",
        "questions": questions,
        "blocking_count": blocking,
        "ready_for_research": (not running) and blocking == 0,
        "framing": framing,
        "running": running,
        "error": state.get("framing_error"),
    }


def build_research_status(state: dict[str, Any]) -> dict[str, Any]:
    status = state.get("status")
    phases = state.get("phases") if isinstance(state.get("phases"), dict) else {}
    investigation = phases.get("investigation", {}) if isinstance(phases.get("investigation"), dict) else {}
    proposal = phases.get("proposal", {}) if isinstance(phases.get("proposal"), dict) else {}
    if status in RESEARCH_RUNNING_STATUSES:
        stage = "investigating" if status == "INVESTIGATING" else "designing"
        return {"state": "running", "stage": stage}
    if status == "FRAMING_REVIEW":
        return {"state": "pending", "stage": None}
    if status in {"WAITING_FOR_ALIGNMENT", "READY_TO_START", "IMPLEMENTING_AND_TESTING", "REVIEWING", "WAITING_FOR_HUMAN", "DONE"}:
        return {"state": "done", "stage": None}
    return {
        "state": "pending" if investigation.get("status") in {None, "pending"} else "done",
        "stage": None,
    }


def build_design_package(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {str(item.get("name")): item for item in artifacts}
    package = [
        {"name": "Framing", "file": "framing.md", "description": "Problem statement, non-goals, assumptions."},
        {"name": "Dossier", "file": "dossier.md", "description": "Current-state research and affected code."},
        {"name": "Proposal", "file": "proposal.md", "description": "Recommended approach, alternatives, risks."},
        {"name": "Acceptance", "file": "acceptance.md", "description": "Acceptance criteria the implementation must satisfy."},
        {"name": "Test plan", "file": "test-plan.md", "description": "How the work will be verified."},
    ]
    for entry in package:
        artifact = by_name.get(entry["file"])
        entry["ready"] = artifact is not None
        entry["path"] = artifact.get("path") if artifact else None
    return package


def build_execution_approval(state: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if state.get("status") != "WAITING_FOR_ALIGNMENT":
        return None
    artifact_names = {str(item.get("name")) for item in artifacts}
    required_artifacts = ["framing.md", "dossier.md", "proposal.md", "acceptance.md", "acceptance.json", "test-plan.md"]
    missing = [name for name in required_artifacts if name not in artifact_names]
    return {
        "required": True,
        "meaning": "Review the framing, dossier, proposal, acceptance, and test plan before execution starts.",
        "primary_action": "Approve and run",
        "missing_artifacts": missing,
        "design_package": build_design_package(artifacts),
    }


def list_task_artifacts(root: Path, task_id: str) -> list[dict[str, Any]]:
    base = task_dir(root, task_id) / "artifacts"
    if not base.exists():
        return []
    artifacts: list[dict[str, Any]] = []
    for path in sorted(item for item in base.iterdir() if item.is_file()):
        artifacts.append(
            {
                "name": path.name,
                "path": path.resolve().relative_to(root.resolve()).as_posix(),
                "size": path.stat().st_size,
                "updated_at": path.stat().st_mtime,
                "preview": bounded_text(path),
            }
        )
    return artifacts


def _latest_iteration(root: Path, task_id: str, state: dict[str, Any]) -> int:
    candidates: list[int] = []
    value = state.get("iteration")
    if isinstance(value, int):
        candidates.append(value)
    for agent in state.get("agents") or []:
        if isinstance(agent, dict) and isinstance(agent.get("iteration"), int):
            candidates.append(agent["iteration"])
    run_root = agentloop_path(root) / "runs" / task_id
    if run_root.exists():
        for item in run_root.iterdir():
            if item.is_dir() and item.name.isdigit():
                candidates.append(int(item.name))
    return max(candidates or [0])


def _agent_log(root: Path, relative: Any) -> dict[str, Any] | None:
    if not isinstance(relative, str) or not relative:
        return None
    try:
        return bounded_workspace_file(root, relative)
    except WorkspaceError as exc:
        return {"missing": True, "exists": False, "error": str(exc), "content": ""}


def _agent_iteration(agent: dict[str, Any]) -> int | None:
    value = agent.get("iteration")
    if isinstance(value, int):
        return value
    for key in ("stdout_log", "stderr_log"):
        log_ref = agent.get(key)
        if not isinstance(log_ref, str):
            continue
        for part in Path(log_ref).parts:
            if part.isdigit():
                return int(part)
    return None


def _latest_review_test_results(root: Path, task_id: str) -> list[dict[str, Any]]:
    artifacts_dir = task_dir(root, task_id) / "artifacts"
    if not artifacts_dir.exists():
        return []
    review_paths = sorted(
        (path for path in artifacts_dir.glob("review-*.json") if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for path in review_paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("test_results"), list):
            continue
        return [item for item in data["test_results"] if isinstance(item, dict)]
    return []


def latest_review_summary(root: Path, task_id: str) -> dict[str, Any] | None:
    artifacts_dir = task_dir(root, task_id) / "artifacts"
    if not artifacts_dir.exists():
        return None
    review_paths = sorted(
        (path for path in artifacts_dir.glob("review-*.json") if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for path in review_paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            artifact_ref = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            artifact_ref = path.as_posix()
        return {
            "artifact": artifact_ref,
            "decision": data.get("decision"),
            "summary": data.get("summary"),
            "comments": data.get("comments") if isinstance(data.get("comments"), list) else [],
            "test_results": data.get("test_results") if isinstance(data.get("test_results"), list) else [],
        }
    return None


def build_human_review(root: Path, task_id: str, state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("status") != "WAITING_FOR_HUMAN":
        return None
    review = latest_review_summary(root, task_id)
    return {
        "required": True,
        "meaning": "AgentLoop paused because the reviewer marked this task as blocked. Automatic iteration will not continue until a human reviews the blocker and resumes the task.",
        "review": review,
        "history": state.get("human_reviews") if isinstance(state.get("human_reviews"), list) else [],
    }


def _test_command_from_log(log: dict[str, Any]) -> str | None:
    lines = str(log.get("content") or "").splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "COMMAND":
            continue
        command_lines: list[str] = []
        for candidate in lines[index + 1 :]:
            stripped = candidate.strip()
            if stripped in {"STDOUT", "STDERR"}:
                break
            if not stripped:
                if command_lines:
                    break
                continue
            command_lines.append(candidate)
        command = "\n".join(command_lines).strip()
        return command or None
    return None


def _test_log_name(result: dict[str, Any]) -> str | None:
    log_ref = result.get("log")
    if isinstance(log_ref, str) and log_ref:
        return Path(log_ref).name
    return None


def _test_result_entry(name: str, result: dict[str, Any] | None, log: dict[str, Any]) -> dict[str, Any]:
    result = result or {}
    command = result.get("command") if isinstance(result.get("command"), str) else _test_command_from_log(log)
    return {
        "name": name,
        "command": command,
        "exit_code": result.get("exit_code"),
        "duration_ms": result.get("duration_ms"),
        "log": log,
    }


def _test_log_summary(root: Path, task_id: str, latest: int) -> list[dict[str, Any]]:
    tests_dir = agentloop_path(root) / "runs" / task_id / f"{latest:03d}" / "tests"
    structured = _latest_review_test_results(root, task_id)
    by_log_name = {_test_log_name(item): item for item in structured if _test_log_name(item)}
    by_command = {item.get("command"): item for item in structured if isinstance(item.get("command"), str)}
    used: set[int] = set()
    tests: list[dict[str, Any]] = []

    if tests_dir.exists():
        for index, path in enumerate(sorted(tests_dir.glob("*.log"))):
            log = bounded_text(path)
            command = _test_command_from_log(log)
            result = by_log_name.get(path.name) or by_command.get(command)
            if result is None and index < len(structured):
                result = structured[index]
            if result is not None:
                used.add(id(result))
            tests.append(_test_result_entry(path.name, result, log))

    for result in structured:
        if id(result) in used:
            continue
        name = _test_log_name(result) or f"test-{len(tests) + 1:02d}"
        log_ref = result.get("log")
        if isinstance(log_ref, str) and log_ref:
            log = _agent_log(root, log_ref) or {"missing": True, "exists": False, "content": ""}
        else:
            log = {"path": None, "exists": False, "missing": True, "truncated": False, "bytes_total": 0, "bytes_returned": 0, "content": ""}
        tests.append(_test_result_entry(name, result, log))

    return tests


def latest_runtime_summary(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    task_id = str(state.get("task_id") or "")
    latest = _latest_iteration(root, task_id, state) if task_id else 0
    run_root = agentloop_path(root) / "runs" / task_id
    run_iterations: set[int] = set()
    if task_id and run_root.exists():
        run_iterations = {int(item.name) for item in run_root.iterdir() if item.is_dir() and item.name.isdigit()}
    iterations = sorted(
        {latest}
        | {int(a.get("iteration")) for a in state.get("agents") or [] if isinstance(a, dict) and isinstance(a.get("iteration"), int)}
        | run_iterations
    )

    agents_by_iter: dict[int, list[dict[str, Any]]] = {n: [] for n in iterations}
    for agent in state.get("agents") or []:
        if not isinstance(agent, dict):
            continue
        agent_iter = _agent_iteration(agent)
        if agent_iter is None:
            agent_iter = latest
        entry = {
            "role": agent.get("role"),
            "runtime": agent.get("runtime"),
            "adapter": agent.get("adapter"),
            "command": agent.get("command"),
            "exit_code": agent.get("exit_code"),
            "duration_ms": agent.get("duration_ms"),
            "artifacts": agent.get("artifacts") or [],
            "stdout": _agent_log(root, agent.get("stdout_log")),
            "stderr": _agent_log(root, agent.get("stderr_log")),
            "iteration": agent_iter,
        }
        agents_by_iter.setdefault(agent_iter, []).append(entry)

    tests_by_iter: dict[int, list[dict[str, Any]]] = {}
    if task_id:
        for n in iterations:
            tests_by_iter[n] = _test_log_summary(root, task_id, n)

    by_iteration = []
    for n in iterations:
        a = agents_by_iter.get(n, [])
        t = tests_by_iter.get(n, [])
        passed = sum(1 for x in t if x.get("exit_code") == 0)
        failed = sum(1 for x in t if isinstance(x.get("exit_code"), int) and x.get("exit_code") != 0)
        by_iteration.append({
            "iteration": n,
            "agents": a,
            "tests": t,
            "agent_count": len(a),
            "test_count": len(t),
            "tests_passed": passed,
            "tests_failed": failed,
        })

    return {
        "iterations": iterations,
        "latest_iteration": latest,
        "agents": agents_by_iter.get(latest, []),
        "tests": tests_by_iter.get(latest, []),
        "by_iteration": by_iteration,
    }


def build_context_view(root: Path, task_id: str, state: dict[str, Any]) -> dict[str, Any]:
    context_log = state.get("context_log") if isinstance(state.get("context_log"), list) else []
    role_sessions = state.get("role_sessions") if isinstance(state.get("role_sessions"), dict) else {}
    entries: list[dict[str, Any]] = []
    for item in context_log:
        if not isinstance(item, dict):
            continue
        entries.append({
            "role": item.get("role"),
            "turn": item.get("turn"),
            "runtime": item.get("runtime"),
            "handoff_ref": item.get("handoff_ref"),
            "handoff_present": item.get("handoff_present"),
            "transcript_ref": item.get("transcript_ref"),
            "session_id": item.get("session_id"),
            "resumed": item.get("resumed"),
            "at": item.get("at") or item.get("written_at"),
        })
    sessions: list[dict[str, Any]] = []
    for key, value in role_sessions.items():
        if not isinstance(value, dict):
            continue
        sessions.append({
            "role": value.get("role") or key,
            "runtime": value.get("runtime"),
            "session_id": value.get("session_id"),
            "updated_at": value.get("updated_at"),
            "turns": value.get("turns"),
        })
    transcripts = list_transcripts(root, task_id)
    return {
        "context_log": entries,
        "role_sessions": sessions,
        "transcripts": transcripts,
    }


def read_transcript(root: Path, task_id: str, role: str, turn: int) -> dict[str, Any]:
    data = load_transcript(root, task_id, role, turn)
    if data is None:
        raise WorkspaceError(f"Transcript not found: {role}-{turn:03d}")
    return data


def build_task_detail(root: Path, task_id: str) -> dict[str, Any]:
    task_state_path(root, task_id)
    errors: list[str] = []
    try:
        state = load_task_state(root, task_id)
    except WorkspaceError as exc:
        state = {**default_state(), "task_id": task_id, "title": task_id, "status": "UNKNOWN"}
        errors.append(str(exc))
    lock_reason = _lock_error(root, task_id)
    try:
        override = load_task_config(root, task_id)
    except WorkspaceError as exc:
        override = {}
        errors.append(str(exc))
    try:
        merged = effective_config(root, task_id)
    except WorkspaceError as exc:
        merged = {}
        errors.append(str(exc))
    artifacts = list_task_artifacts(root, task_id)
    return {
        "state": {
            "task_id": task_id,
            "title": _title_from_state(state, task_id),
            "status": state.get("status"),
            "current_phase": state.get("current_phase"),
            "iteration": state.get("iteration"),
            "max_iterations": state.get("max_iterations") or merged.get("max_iterations"),
            "requires_human_approval": state.get("requires_human_approval"),
            "goal": state.get("goal") or {},
            "framing": state.get("framing") or {},
            "acceptance_criteria": state.get("acceptance_criteria") or [],
            "phases": state.get("phases") or {},
            "created_at": state.get("created_at"),
            "updated_at": state.get("updated_at"),
            "cancelled_from": state.get("cancelled_from"),
            "cancelled_by": state.get("cancelled_by"),
            "cancelled_at": state.get("cancelled_at"),
        },
        "config": {"override": override, "effective": merged},
        "actions": available_actions(state, lock_reason),
        "artifacts": artifacts,
        "runtime": latest_runtime_summary(root, state),
        "framing_review": build_framing_review(state),
        "research_status": build_research_status(state),
        "design_package": build_design_package(artifacts),
        "execution_approval": build_execution_approval(state, artifacts),
        "human_review": build_human_review(root, task_id, state),
        "context": build_context_view(root, task_id, state),
        "errors": errors,
    }


def create_task(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request")
    if not isinstance(request, str) or not request.strip():
        raise WorkspaceError("request must be a non-empty string.")
    code_path = payload.get("code_path")
    if not isinstance(code_path, str) or not code_path.strip():
        raise WorkspaceError("code_path must be a non-empty string.")
    role_runtimes = payload.get("role_runtimes")
    config_override: dict[str, Any] = {}
    max_iterations = payload.get("max_iterations")
    if max_iterations is not None:
        try:
            max_iter_int = int(max_iterations)
        except (TypeError, ValueError) as exc:
            raise WorkspaceError("max_iterations must be a positive integer.") from exc
        if max_iter_int < 1:
            raise WorkspaceError("max_iterations must be a positive integer.")
        config_override["max_iterations"] = max_iter_int
    if role_runtimes is not None:
        if not isinstance(role_runtimes, dict):
            raise WorkspaceError("role_runtimes must be an object.")
        config = load_config(root)
        known_runtimes = config.get("runtimes", {}) if isinstance(config.get("runtimes"), dict) else {}
        roles: dict[str, dict[str, str]] = {}
        for role, runtime_name in role_runtimes.items():
            if role not in VALID_ROLES:
                raise WorkspaceError(f"Unknown role: {role}")
            if not isinstance(runtime_name, str) or runtime_name not in known_runtimes:
                raise WorkspaceError(f"Unknown runtime for role {role}: {runtime_name}")
            roles[role] = {"runtime": runtime_name}
        if roles:
            config_override["roles"] = roles
    state = start_task(
        root,
        request,
        config_override=config_override or None,
        code_path=code_path,
    )
    return build_task_detail(root, str(state["task_id"]))


def submit_framing_answers_api(root: Path, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}
    by = payload.get("by") if isinstance(payload.get("by"), str) else "ui"
    normalized = {str(k): str(v) for k, v in answers.items()}
    with task_lock(root, task_id, blocking=False):
        submit_framing_answers(root, task_id, normalized, by=by)
    return build_task_detail(root, task_id)


def start_research_api(root: Path, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with task_lock(root, task_id, blocking=False):
        start_research(root, task_id)
    return build_task_detail(root, task_id)


def patch_task_config(root: Path, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"test_commands"}
    patch = {key: payload[key] for key in allowed if key in payload}
    unknown = set(payload) - allowed
    if unknown:
        raise WorkspaceError(f"Unsupported config keys: {', '.join(sorted(unknown))}")
    with task_lock(root, task_id, blocking=False):
        save_task_config_patch(root, task_id, patch)
    return build_task_detail(root, task_id)


def delete_task(root: Path, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("confirm") != task_id:
        raise WorkspaceError("Delete confirmation must match the task id exactly.")
    with task_lock(root, task_id, blocking=False):
        target = task_dir(root, task_id)
        base = (agentloop_path(root) / "tasks").resolve()
        if not str(target.resolve()).lower().startswith(str(base).lower()):
            raise WorkspaceError("Invalid task path.")
        if not target.exists():
            raise WorkspaceError(f"Task does not exist: {task_id}")
    try:
        shutil.rmtree(target, onerror=_force_remove_readonly)
    except OSError as exc:
        raise WorkspaceError(f"Failed to delete task {task_id}: {exc}") from exc
    if current_task_id(root) == task_id:
        save_state(root, default_state())
        set_current_task_id(root, None)
    return {"deleted": True, "task_id": task_id}


def _force_remove_readonly(func: Any, path: str, _exc_info: Any) -> None:
    try:
        os.chmod(path, 0o700)
        func(path)
    except OSError as exc:
        raise WorkspaceError(f"Could not remove {path}: {exc}") from exc


def approve_task_api(root: Path, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    by = payload.get("by") if isinstance(payload.get("by"), str) else "requester"
    with task_lock(root, task_id, blocking=False):
        approve_task(root, approved_by=by, task_id=task_id)
        run_task(root, task_id=task_id)
    return build_task_detail(root, task_id)


def cancel_task_api(root: Path, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    by = payload.get("by") if isinstance(payload.get("by"), str) else "requester"
    with task_lock(root, task_id, blocking=False):
        cancel_task(root, cancelled_by=by, task_id=task_id)
    return build_task_detail(root, task_id)


def run_task_api(root: Path, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    wait = bool(payload.get("wait", False))
    with task_lock(root, task_id, blocking=wait):
        run_task(root, task_id=task_id)
    return build_task_detail(root, task_id)


def resume_task_api(root: Path, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .tasks import save_task_state
    from .models import utc_now_iso

    note = payload.get("note") if isinstance(payload.get("note"), str) else ""
    by = payload.get("by") if isinstance(payload.get("by"), str) else "ui"
    with task_lock(root, task_id, blocking=False):
        state = load_task_state(root, task_id)
        if state.get("status") != "WAITING_FOR_HUMAN":
            raise WorkspaceError(f"Cannot resume while status is {state.get('status')}.")
        now = utc_now_iso()
        latest_review = latest_review_summary(root, task_id)
        state.setdefault("human_reviews", []).append(
            {
                "at": now,
                "by": by,
                "action": "resume",
                "note": note.strip(),
                "from_review": latest_review.get("artifact") if latest_review else None,
            }
        )
        state["status"] = "IMPLEMENTING_AND_TESTING"
        state["current_phase"] = "implementation"
        state["requires_human_approval"] = False
        state["updated_at"] = now
        save_task_state(root, task_id, state)
    return build_task_detail(root, task_id)


def read_artifact(root: Path, task_id: str, name: str) -> dict[str, Any]:
    if not name or name.startswith(".") or "/" in name or "\\" in name:
        raise WorkspaceError("Invalid artifact name.")
    base = task_dir(root, task_id) / "artifacts"
    path = resolve_under(base, name)
    if not path.exists():
        raise WorkspaceError(f"Artifact not found: {name}")
    payload = bounded_text(path)
    payload["path"] = path.resolve().relative_to(root.resolve()).as_posix()
    payload["name"] = name
    return payload


_EDITABLE_ARTIFACT_NAMES = {"proposal.md", "acceptance.md", "acceptance.json", "test-plan.md", "dossier.md"}


def _edited_name(base: str) -> str:
    stem, dot, ext = base.rpartition(".")
    return f"{stem}.edited.{ext}" if dot else f"{base}.edited"


def edit_artifact_api(root: Path, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = payload.get("name") if isinstance(payload.get("name"), str) else ""
    if not name or name.startswith(".") or "/" in name or "\\" in name:
        raise WorkspaceError("Invalid artifact name.")
    base_lower = name.lower()
    if base_lower not in _EDITABLE_ARTIFACT_NAMES:
        raise WorkspaceError(f"Artifact {name} is not editable.")
    content = payload.get("content")
    with task_lock(root, task_id, blocking=False):
        state = load_task_state(root, task_id)
        if state.get("status") != "WAITING_FOR_ALIGNMENT":
            raise WorkspaceError("Edits are only allowed while awaiting approval.")
        artifacts_dir = task_dir(root, task_id) / "artifacts"
        edited_path = resolve_under(artifacts_dir, _edited_name(name))
        if content is None:
            if edited_path.exists():
                edited_path.unlink()
            return {"name": name, "edited": False}
        if not isinstance(content, str):
            raise WorkspaceError("content must be a string.")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        edited_path.write_text(content, encoding="utf-8")
    return {"name": name, "edited": True, "edited_name": _edited_name(name)}



def error_payload(exc: Exception) -> dict[str, Any]:
    code = "lock_held" if isinstance(exc, LockHeld) else "workspace_error"
    return {"error": {"code": code, "message": str(exc)}}
