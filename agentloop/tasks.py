"""Per-task discovery, IO, configuration merge, resolver, and migration."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

from .models import default_config, default_state
from .workspace import (
    WorkspaceError,
    agentloop_path,
    load_config,
    state_path,
    write_json,
)


TERMINAL_STATUSES = {"DONE", "CANCELLED"}
INACTIVE_STATUSES = {"CREATED"} | TERMINAL_STATUSES


def tasks_dir(root: Path) -> Path:
    return agentloop_path(root) / "tasks"


def task_dir(root: Path, task_id: str) -> Path:
    if not task_id or task_id in {".", ".."} or any(sep in task_id for sep in ["/", "\\"]):
        raise WorkspaceError(f"Invalid task_id: {task_id}")
    base = tasks_dir(root)
    target = (base / task_id).resolve()
    if not str(target).lower().startswith(str(base.resolve()).lower()):
        raise WorkspaceError(f"Invalid task path: {task_id}")
    return target


def task_state_path(root: Path, task_id: str) -> Path:
    return task_dir(root, task_id) / "state.json"


def task_config_path(root: Path, task_id: str) -> Path:
    return task_dir(root, task_id) / "config.json"


def list_task_ids(root: Path) -> list[str]:
    base = tasks_dir(root)
    if not base.exists():
        return []
    return sorted(item.name for item in base.iterdir() if item.is_dir())


def load_task_state(root: Path, task_id: str) -> dict[str, Any]:
    path = task_state_path(root, task_id)
    if not path.exists():
        raise WorkspaceError(f"Task state not found: {task_id}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Invalid task state: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError(f"Invalid task state: {path}: expected object")
    if not isinstance(data.get("context_log"), list):
        data["context_log"] = []
    if not isinstance(data.get("role_sessions"), dict):
        data["role_sessions"] = {}
    return data


def save_task_state(root: Path, task_id: str, state: dict[str, Any]) -> None:
    write_json(task_state_path(root, task_id), state)
    pointer = _read_pointer(root)
    current = pointer.get("current_task_id") or pointer.get("task_id")
    if current is None or current == task_id:
        # Mirror to legacy global state for backwards compatibility.
        write_json(state_path(root), state)


def _read_pointer(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def set_current_task_id(root: Path, task_id: str | None) -> None:
    pointer = _read_pointer(root)
    if not pointer:
        pointer = default_state()
    pointer["task_id"] = task_id
    if task_id:
        try:
            state = load_task_state(root, task_id)
            write_json(state_path(root), state)
            return
        except WorkspaceError:
            pass
    write_json(state_path(root), pointer)


def current_task_id(root: Path) -> str | None:
    value = _read_pointer(root).get("task_id")
    return value if isinstance(value, str) and value else None


def active_task_ids(root: Path) -> list[str]:
    out: list[str] = []
    for tid in list_task_ids(root):
        try:
            state = load_task_state(root, tid)
        except WorkspaceError:
            continue
        if state.get("status") not in INACTIVE_STATUSES:
            out.append(tid)
    return out


def task_snapshot(root: Path, task_id: str) -> dict[str, Any]:
    try:
        return load_task_state(root, task_id)
    except WorkspaceError:
        return {"task_id": task_id, "title": "-", "status": "UNKNOWN", "iteration": "-"}


def resolve_task_id(root: Path, explicit: str | None) -> str:
    if explicit:
        # Validate exists
        task_state_path(root, explicit)
        if not task_state_path(root, explicit).exists():
            raise WorkspaceError(f"Task does not exist: {explicit}")
        return explicit
    actives = active_task_ids(root)
    if len(actives) == 1:
        return actives[0]
    if not actives:
        current = current_task_id(root)
        if current and task_state_path(root, current).exists():
            return current
        raise WorkspaceError("No active task. Pass --task-id <id> or run `agentloop start`.")
    lines = ["multiple active tasks; pass --task-id <id>. Candidates:"]
    for tid in actives:
        snap = task_snapshot(root, tid)
        status = snap.get("status", "-")
        iteration = snap.get("iteration", "-")
        max_it = snap.get("max_iterations", "-")
        lines.append(f"  - {tid}  {status} (it {iteration}/{max_it})")
    raise WorkspaceError("\n".join(lines))


# ---------- per-task config ----------

ALLOWED_TOP_KEYS = {"test_commands", "max_iterations", "roles", "default_runtime"}


def load_task_config(root: Path, task_id: str) -> dict[str, Any]:
    path = task_config_path(root, task_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Invalid task config: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError(f"Invalid task config: {path}: expected object")
    return data


def save_task_config(root: Path, task_id: str, config: dict[str, Any]) -> None:
    path = task_config_path(root, task_id)
    if config:
        write_json(path, config)
    elif path.exists():
        path.unlink()


def save_task_config_patch(root: Path, task_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Atomically merge and validate a top-level per-task config patch."""

    override = load_task_config(root, task_id)
    merged = {**override, **patch}
    _validate_patch(merged, load_config(root))
    save_task_config(root, task_id, merged)
    return merged


def clear_task_config(root: Path, task_id: str) -> None:
    path = task_config_path(root, task_id)
    if path.exists():
        path.unlink()


def effective_config(root: Path, task_id: str | None) -> dict[str, Any]:
    global_cfg: dict[str, Any]
    try:
        global_cfg = copy.deepcopy(load_config(root))
    except WorkspaceError:
        global_cfg = default_config()

    if not task_id:
        return global_cfg

    override = load_task_config(root, task_id)
    if not override:
        return global_cfg

    merged = copy.deepcopy(global_cfg)
    if "test_commands" in override:
        merged["test_commands"] = list(override["test_commands"])
    if "max_iterations" in override:
        merged["max_iterations"] = override["max_iterations"]
    if "default_runtime" in override:
        merged["default_runtime"] = override["default_runtime"]
    if "roles" in override and isinstance(override["roles"], dict):
        roles = merged.setdefault("roles", {})
        for role, role_cfg in override["roles"].items():
            base = roles.get(role, {})
            if isinstance(role_cfg, dict):
                merged_role = {**base, **role_cfg}
            else:
                merged_role = role_cfg
            roles[role] = merged_role
    return merged


def _validate_patch(patch: dict[str, Any], global_cfg: dict[str, Any]) -> None:
    unknown = set(patch) - ALLOWED_TOP_KEYS
    if unknown:
        raise WorkspaceError(
            f"Unknown override keys: {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(ALLOWED_TOP_KEYS))}"
        )
    if "test_commands" in patch:
        value = patch["test_commands"]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise WorkspaceError("test_commands must be a list of strings.")
    if "max_iterations" in patch:
        value = patch["max_iterations"]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise WorkspaceError("max_iterations must be a positive integer.")
    runtimes = global_cfg.get("runtimes", {}) if isinstance(global_cfg, dict) else {}
    if "default_runtime" in patch:
        if patch["default_runtime"] not in runtimes:
            raise WorkspaceError(f"Unknown runtime: {patch['default_runtime']}")
    if "roles" in patch:
        if not isinstance(patch["roles"], dict):
            raise WorkspaceError("roles override must be an object.")
        for role, role_cfg in patch["roles"].items():
            if not isinstance(role_cfg, dict):
                raise WorkspaceError(f"roles.{role} must be an object.")
            runtime_name = role_cfg.get("runtime")
            if runtime_name is not None and runtime_name not in runtimes:
                raise WorkspaceError(f"Unknown runtime for role {role}: {runtime_name}")


def _set_dotted(target: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    cur = target
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _unset_dotted(target: dict[str, Any], dotted_key: str) -> None:
    parts = dotted_key.split(".")
    cur = target
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            return
        cur = nxt
    cur.pop(parts[-1], None)


def apply_task_config_patch(
    root: Path,
    task_id: str,
    key: str,
    value: Any,
) -> dict[str, Any]:
    override = load_task_config(root, task_id)
    _set_dotted(override, key, value)
    _validate_patch(override, load_config(root))
    save_task_config(root, task_id, override)
    return override


def unset_task_config_key(root: Path, task_id: str, key: str) -> dict[str, Any]:
    override = load_task_config(root, task_id)
    _unset_dotted(override, key)
    # Prune empty containers
    if "roles" in override and isinstance(override["roles"], dict):
        override["roles"] = {k: v for k, v in override["roles"].items() if v}
        if not override["roles"]:
            override.pop("roles")
    save_task_config(root, task_id, override)
    return override


# ---------- migration ----------

MIGRATION_MARKER = "MIGRATED"


def migrate_workspace(root: Path) -> dict[str, Any]:
    """Idempotent migration to per-task state layout. Returns summary."""

    base = agentloop_path(root)
    if not base.exists():
        return {"migrated": False, "reason": "no .agentloop directory"}

    (base / "tasks").mkdir(parents=True, exist_ok=True)
    (base / "runs").mkdir(parents=True, exist_ok=True)
    (base / "locks").mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {"copied_state": False, "moved_runs": [], "task_id": None}

    legacy = state_path(root)
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            tid = data.get("task_id")
            if isinstance(tid, str) and tid:
                summary["task_id"] = tid
                per_task = task_state_path(root, tid)
                if not per_task.exists():
                    write_json(per_task, data)
                    summary["copied_state"] = True

    # Move legacy runs/NNN to runs/<current_task_id>/NNN if a current task exists.
    current = current_task_id(root)
    runs_dir = base / "runs"
    if current and runs_dir.exists():
        for child in list(runs_dir.iterdir()):
            if not child.is_dir():
                continue
            # Iteration dirs are 3-digit numerics. Task ids start with date prefix.
            if child.name.isdigit():
                target = runs_dir / current / child.name
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(child), str(target))
                    summary["moved_runs"].append(child.name)

    (base / MIGRATION_MARKER).write_text("ok\n", encoding="utf-8")
    return summary


# ---------- selectors ----------


def select_task_ids(
    root: Path,
    *,
    task_ids: list[str] | None = None,
    all_tasks: bool = False,
    statuses: list[str] | None = None,
) -> list[str]:
    modes = sum(1 for m in [bool(task_ids), all_tasks, bool(statuses)] if m)
    if modes == 0:
        raise WorkspaceError("Selector required: --task-id, --all, or --status.")
    if modes > 1:
        raise WorkspaceError("Selectors are mutually exclusive: choose one of --task-id, --all, --status.")
    if task_ids:
        for tid in task_ids:
            if not task_state_path(root, tid).exists():
                raise WorkspaceError(f"Task does not exist: {tid}")
        return list(task_ids)
    if all_tasks:
        return list_task_ids(root)
    wanted = {s.upper() for s in (statuses or [])}
    out = []
    for tid in list_task_ids(root):
        snap = task_snapshot(root, tid)
        if str(snap.get("status", "")).upper() in wanted:
            out.append(tid)
    return out
