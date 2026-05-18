"""Command-line interface for AgentLoop."""

from __future__ import annotations

import argparse
import json
import shutil
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import add_command_runtime, add_preset_runtime, assign_all_runtime, assign_runtime, detect_runtimes, list_runtimes, set_default_runtime
from .locks import LockHeld, lock_path, task_lock
from .models import default_state, next_action
from .tasks import (
    INACTIVE_STATUSES,
    active_task_ids,
    apply_task_config_patch,
    clear_task_config,
    current_task_id,
    effective_config,
    list_task_ids,
    load_task_config,
    load_task_state,
    migrate_workspace,
    resolve_task_id,
    save_task_state,
    select_task_ids,
    set_current_task_id,
    task_dir,
    task_snapshot,
    task_state_path,
    unset_task_config_key,
)
from .verify import verify_runtime
from .workspace import WorkspaceError, agentloop_path, init_workspace, load_config, load_state, save_state
from .workflow import approve_task, cancel_task, run_task, start_task


def configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _add_task_id_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("task_id", nargs="?", default=None, help="Optional task id. Defaults to the single active task.")
    parser.add_argument("--task-id", dest="task_id_opt", default=None, help="Task id selector (alternative to positional).")


def _add_selector_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task-id", dest="task_ids", action="append", default=[], help="Target task id (repeatable).")
    parser.add_argument("--all", dest="all_tasks", action="store_true", help="Target every task in the workspace.")
    parser.add_argument("--status", dest="statuses", action="append", default=[], help="Target every task with this status (repeatable).")
    parser.add_argument("--dry-run", action="store_true", help="Print the selection without acting.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentloop",
        description="Local, agent-agnostic orchestration for coding tasks.",
    )
    parser.add_argument("--root", default=".", help="Workspace root. Defaults to the current directory.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize .agentloop in the workspace.")
    init_parser.add_argument("--detect-runtimes", action="store_true", help="Detect local Codex/Claude/Copilot runtimes after init.")
    init_parser.add_argument("--replace-runtimes", action="store_true", help="Replace existing detected runtime entries during --detect-runtimes.")
    status_parser = subparsers.add_parser("status", help="Show task status.")
    _add_task_id_argument(status_parser)

    tasks_parser = subparsers.add_parser("tasks", help="Inventory, batch lifecycle, per-task config, locks.")
    tasks_subparsers = tasks_parser.add_subparsers(dest="tasks_command")

    list_parser = tasks_subparsers.add_parser("list", help="List AgentLoop tasks.")
    list_parser.add_argument("--status", dest="statuses", action="append", default=[], help="Filter by status (repeatable).")
    list_parser.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON.")

    tasks_delete_parser = tasks_subparsers.add_parser("delete", help="Delete one task by task_id.")
    tasks_delete_parser.add_argument("task_id", help="Task id to delete.")
    tasks_subparsers.add_parser("delete-all", aliases=["clear"], help="Delete all tasks and reset current state.")

    # Batch lifecycle
    for op in ("approve", "cancel"):
        sp = tasks_subparsers.add_parser(op, help=f"Batch {op} multiple tasks.")
        _add_selector_arguments(sp)
        sp.add_argument("--by", default="requester", help=f"Name recorded as {op}-er.")
    run_batch = tasks_subparsers.add_parser("run", help="Batch run multiple tasks.")
    _add_selector_arguments(run_batch)
    run_batch.add_argument("--wait", action="store_true", help="Wait for per-task lock instead of failing fast.")
    run_batch.add_argument("--parallel", type=int, default=1, help="Number of concurrent runs (default 1).")

    unlock_parser = tasks_subparsers.add_parser("unlock", help="Remove a stale task lock.")
    unlock_parser.add_argument("task_id", help="Task id to unlock.")

    tasks_subparsers.add_parser("migrate", help="Run workspace migration (idempotent).")

    # Config subgroup
    config_parser = tasks_subparsers.add_parser("config", help="Per-task config overrides.")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    cfg_show = config_subparsers.add_parser("show", help="Show per-task config or effective merged config.")
    cfg_show.add_argument("task_id")
    cfg_show.add_argument("--effective", action="store_true", help="Show merged effective config instead of the raw override.")
    cfg_set = config_subparsers.add_parser("set", help="Set a per-task config key on one or more tasks.")
    _add_selector_arguments(cfg_set)
    cfg_set.add_argument("key", help="Dotted key, e.g. test_commands, max_iterations, roles.reviewer.runtime")
    cfg_set.add_argument("value", help="Value (string by default).")
    cfg_set.add_argument("--json", dest="value_is_json", action="store_true", help="Treat value as JSON.")
    cfg_unset = config_subparsers.add_parser("unset", help="Remove a per-task config key on one or more tasks.")
    _add_selector_arguments(cfg_unset)
    cfg_unset.add_argument("key")
    cfg_clear = config_subparsers.add_parser("clear", help="Delete per-task config override file(s) entirely.")
    _add_selector_arguments(cfg_clear)

    start_parser = subparsers.add_parser("start", help="Start a task and draft analysis artifacts.")
    start_parser.add_argument("task", help="Task request to analyze.")

    approve_parser = subparsers.add_parser("approve", help="Approve the analysis and acceptance criteria.")
    _add_task_id_argument(approve_parser)
    approve_parser.add_argument("--by", default="requester", help="Name to record as the approver. Defaults to requester.")

    cancel_parser = subparsers.add_parser("cancel", help="Cancel a task.")
    _add_task_id_argument(cancel_parser)
    cancel_parser.add_argument("--by", default="requester", help="Name to record as the canceller.")

    run_parser = subparsers.add_parser("run", help="Run or resume the design/test/review loop.")
    _add_task_id_argument(run_parser)
    run_parser.add_argument("--wait", action="store_true", help="Wait for per-task lock instead of failing fast.")

    runtime_parser = subparsers.add_parser("runtime", help="Manage coding agent runtimes.")
    runtime_subparsers = runtime_parser.add_subparsers(dest="runtime_command", required=True)

    runtime_subparsers.add_parser("list", help="List configured runtimes and role assignments.")
    detect_parser = runtime_subparsers.add_parser("detect", help="Detect local Codex/Claude/Copilot runtime commands.")
    detect_parser.add_argument("--replace", action="store_true", help="Replace existing detected runtime entries.")

    add_command_parser = runtime_subparsers.add_parser("add-command", help="Add a command-based runtime.")
    add_command_parser.add_argument("name", help="Runtime name.")
    add_command_parser.add_argument("--command", dest="runtime_executable", required=True, help="Executable to run.")
    add_command_parser.add_argument("--arg", action="append", default=[], help="Argument (repeatable). Supports {prompt_file}, {cwd}, {role}, {iteration}.")
    add_command_parser.add_argument("--args", default=None, help="Shell-like argument string.")
    add_command_parser.add_argument("--stdin-file", default=None)
    add_command_parser.add_argument("--timeout-seconds", type=int, default=None)
    add_command_parser.add_argument("--set-default", action="store_true")
    add_command_parser.add_argument("--replace", action="store_true")

    add_preset_parser = runtime_subparsers.add_parser("add-preset", help="Add a built-in runtime preset.")
    add_preset_parser.add_argument("preset")
    add_preset_parser.add_argument("--assign", action="append", default=[])
    add_preset_parser.add_argument("--assign-all", action="store_true")
    add_preset_parser.add_argument("--set-default", action="store_true")
    add_preset_parser.add_argument("--replace", action="store_true")

    assign_parser = runtime_subparsers.add_parser("assign", help="Assign a runtime to a role.")
    assign_parser.add_argument("role")
    assign_parser.add_argument("runtime")

    assign_all_parser = runtime_subparsers.add_parser("assign-all", help="Assign a runtime to all roles.")
    assign_all_parser.add_argument("runtime")
    assign_all_parser.add_argument("--except", dest="except_roles", action="append", default=[])

    default_parser = runtime_subparsers.add_parser("set-default", help="Set the default runtime.")
    default_parser.add_argument("runtime")

    verify_parser = runtime_subparsers.add_parser("verify", help="Verify a command runtime can produce AgentLoop artifacts.")
    verify_parser.add_argument("runtime")
    verify_parser.add_argument("--timeout-seconds", type=int, default=300)

    return parser


def _resolve_task_arg(args: argparse.Namespace) -> str | None:
    return getattr(args, "task_id", None) or getattr(args, "task_id_opt", None)


# ---------- simple commands ----------


def print_detect_summary(result: dict[str, Any]) -> None:
    detected = result.get("detected", {})
    installed = set(result.get("installed", []) or [])
    skipped = set(result.get("skipped", []) or [])
    print("Runtime detection:")
    if not detected:
        print("  detected: none")
        print("  next: use `python -m agentloop runtime add-command ...` to configure a runtime manually")
        return
    for name, runtime in sorted(detected.items()):
        status = "installed" if name in installed else "skipped"
        if name in skipped:
            status = "skipped existing"
        print(f"  - {name}: {status} command={runtime.get('command')}")
    print("  next:")
    print("    python -m agentloop runtime assign-all <runtime>")
    print("    python -m agentloop runtime verify <runtime> --timeout-seconds 120")


def cmd_init(root: Path, detect: bool = False, replace_runtimes: bool = False) -> int:
    result = init_workspace(root)
    print("AgentLoop initialized.")
    if result["created"]:
        print("Created:")
        for item in result["created"]:
            print(f"  - {item}")
    if result["skipped"]:
        print("Already existed:")
        for item in result["skipped"]:
            print(f"  - {item}")
    if detect:
        print_detect_summary(detect_runtimes(root, replace=replace_runtimes))
    return 0


def cmd_status(root: Path, explicit_task: str | None) -> int:
    if explicit_task:
        tid = resolve_task_id(root, explicit_task)
        state = load_task_state(root, tid)
        config = effective_config(root, tid)
    else:
        try:
            tid = resolve_task_id(root, None)
            state = load_task_state(root, tid)
            config = effective_config(root, tid)
        except WorkspaceError:
            state = load_state(root)
            config = load_config(root)
    print("AgentLoop status")
    print(f"  task_id: {state.get('task_id') or '-'}")
    print(f"  title: {state.get('title') or '-'}")
    print(f"  status: {state.get('status')}")
    print(f"  current_phase: {state.get('current_phase') or '-'}")
    print(f"  iteration: {state.get('iteration', 0)}/{state.get('max_iterations', config.get('max_iterations', '-'))}")
    print(f"  default_runtime: {config.get('default_runtime', '-')}")
    print(f"  next_action: {next_action(state)}")
    return 0


# ---------- tasks subgroup ----------


def cmd_tasks_list(root: Path, statuses: list[str], as_json: bool) -> int:
    current = current_task_id(root)
    wanted = {s.upper() for s in statuses}
    rows: list[dict[str, Any]] = []
    for tid in list_task_ids(root):
        snap = task_snapshot(root, tid)
        if wanted and str(snap.get("status", "")).upper() not in wanted:
            continue
        rows.append(snap)

    if as_json:
        print(json.dumps([
            {
                "task_id": r.get("task_id"),
                "title": r.get("title"),
                "status": r.get("status"),
                "iteration": r.get("iteration"),
                "max_iterations": r.get("max_iterations"),
                "current": r.get("task_id") == current,
            }
            for r in rows
        ], indent=2))
        return 0

    print("AgentLoop tasks")
    if not rows:
        print("  - none")
        return 0
    for snap in rows:
        marker = "*" if snap.get("task_id") == current else " "
        title = str(snap.get("title") or "-").replace("\n", " ")
        if len(title) > 80:
            title = title[:77] + "..."
        tid = snap.get("task_id")
        print(f"  {marker} {tid}")
        print(f"      status: {snap.get('status', '-')}")
        print(f"      iteration: {snap.get('iteration', '-')}/{snap.get('max_iterations', '-')}")
        print(f"      title: {title}")
        print(f"      artifacts: .agentloop/tasks/{tid}/artifacts/")
    return 0


def reset_current_state(root: Path) -> None:
    save_state(root, default_state())


def delete_task_dir(root: Path, task_id: str) -> bool:
    target = task_dir(root, task_id)
    if not target.exists():
        return False
    if not target.is_dir():
        raise WorkspaceError(f"Task path is not a directory: {task_id}")
    shutil.rmtree(target)
    return True


def clear_run_and_global_artifacts(root: Path) -> None:
    for name in ["runs", "artifacts"]:
        path = agentloop_path(root) / name
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)


def cmd_tasks_delete(root: Path, task_id: str) -> int:
    current = current_task_id(root)
    deleted = delete_task_dir(root, task_id)
    if not deleted:
        raise WorkspaceError(f"Task does not exist: {task_id}")
    if current == task_id:
        reset_current_state(root)
    print("AgentLoop task deleted.")
    print(f"  task_id: {task_id}")
    print(f"  reset_current_state: {'yes' if current == task_id else 'no'}")
    return 0


def cmd_tasks_delete_all(root: Path) -> int:
    tasks = list_task_ids(root)
    for tid in tasks:
        delete_task_dir(root, tid)
    clear_run_and_global_artifacts(root)
    reset_current_state(root)
    print("AgentLoop tasks deleted.")
    print(f"  deleted: {len(tasks)}")
    print("  status: CREATED")
    return 0


def cmd_tasks_unlock(root: Path, task_id: str) -> int:
    path = lock_path(root, task_id)
    if not path.exists():
        print(f"No lock present for task {task_id}.")
        return 0
    path.unlink()
    print(f"Lock removed for task {task_id}.")
    return 0


def cmd_tasks_migrate(root: Path) -> int:
    summary = migrate_workspace(root)
    print("AgentLoop workspace migrated.")
    print(json.dumps(summary, indent=2))
    return 0


# ---------- batch lifecycle helpers ----------


def _resolve_selection(root: Path, args: argparse.Namespace) -> list[str]:
    return select_task_ids(
        root,
        task_ids=list(getattr(args, "task_ids", []) or []),
        all_tasks=bool(getattr(args, "all_tasks", False)),
        statuses=list(getattr(args, "statuses", []) or []),
    )


def _print_batch_summary(label: str, results: list[tuple[str, str, str]]) -> int:
    print(f"AgentLoop batch {label}:")
    failures = 0
    for status, tid, message in results:
        print(f"  - {status:5s}  {tid}  {message}")
        if status != "ok":
            failures += 1
    print(f"  total: {len(results)}  ok: {len(results) - failures}  error: {failures}")
    return 0 if failures == 0 else 1


def _run_batch_op(
    root: Path,
    selection: list[str],
    *,
    op: Callable[[str], str],
    blocking: bool = False,
    parallel: int = 1,
) -> list[tuple[str, str, str]]:
    def runner(tid: str) -> tuple[str, str, str]:
        try:
            with task_lock(root, tid, blocking=blocking):
                message = op(tid)
            return ("ok", tid, message)
        except (WorkspaceError, LockHeld) as exc:
            return ("error", tid, str(exc).replace("\n", " | "))

    if parallel <= 1:
        return [runner(tid) for tid in selection]
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        return list(pool.map(runner, selection))


def cmd_tasks_batch_approve(root: Path, args: argparse.Namespace) -> int:
    selection = _resolve_selection(root, args)
    if args.dry_run:
        print("dry-run selection:")
        for tid in selection:
            print(f"  - {tid}")
        return 0

    def op(tid: str) -> str:
        approve_task(root, approved_by=args.by, task_id=tid)
        return "approved"

    return _print_batch_summary("approve", _run_batch_op(root, selection, op=op))


def cmd_tasks_batch_cancel(root: Path, args: argparse.Namespace) -> int:
    selection = _resolve_selection(root, args)
    if args.dry_run:
        print("dry-run selection:")
        for tid in selection:
            print(f"  - {tid}")
        return 0

    def op(tid: str) -> str:
        cancel_task(root, cancelled_by=args.by, task_id=tid)
        return "cancelled"

    return _print_batch_summary("cancel", _run_batch_op(root, selection, op=op))


def cmd_tasks_batch_run(root: Path, args: argparse.Namespace) -> int:
    selection = _resolve_selection(root, args)
    if args.dry_run:
        print("dry-run selection:")
        for tid in selection:
            print(f"  - {tid}")
        return 0

    def op(tid: str) -> str:
        state = run_task(root, task_id=tid)
        return f"status: {state.get('status')} iteration: {state.get('iteration')}"

    results = _run_batch_op(
        root,
        selection,
        op=op,
        blocking=args.wait,
        parallel=max(1, args.parallel),
    )
    return _print_batch_summary("run", results)


# ---------- per-task config commands ----------


def _parse_value(raw: str, as_json: bool) -> Any:
    if as_json:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WorkspaceError(f"Invalid JSON value: {exc}")
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


def cmd_tasks_config_show(root: Path, task_id: str, show_effective: bool) -> int:
    resolved = resolve_task_id(root, task_id)
    if show_effective:
        data = effective_config(root, resolved)
    else:
        data = load_task_config(root, resolved)
    print(json.dumps(data, indent=2))
    return 0


def cmd_tasks_config_set(root: Path, args: argparse.Namespace) -> int:
    selection = _resolve_selection(root, args)
    value = _parse_value(args.value, args.value_is_json)
    if args.dry_run:
        print("dry-run:")
        for tid in selection:
            print(f"  - set {tid}.{args.key} = {value!r}")
        return 0

    def op(tid: str) -> str:
        apply_task_config_patch(root, tid, args.key, value)
        return f"set {args.key}"

    return _print_batch_summary("config set", _run_batch_op(root, selection, op=op))


def cmd_tasks_config_unset(root: Path, args: argparse.Namespace) -> int:
    selection = _resolve_selection(root, args)
    if args.dry_run:
        print("dry-run:")
        for tid in selection:
            print(f"  - unset {tid}.{args.key}")
        return 0

    def op(tid: str) -> str:
        unset_task_config_key(root, tid, args.key)
        return f"unset {args.key}"

    return _print_batch_summary("config unset", _run_batch_op(root, selection, op=op))


def cmd_tasks_config_clear(root: Path, args: argparse.Namespace) -> int:
    selection = _resolve_selection(root, args)
    if args.dry_run:
        print("dry-run:")
        for tid in selection:
            print(f"  - clear {tid}")
        return 0

    def op(tid: str) -> str:
        clear_task_config(root, tid)
        return "cleared"

    return _print_batch_summary("config clear", _run_batch_op(root, selection, op=op))


# ---------- single-task lifecycle ----------


def cmd_start(root: Path, task: str) -> int:
    state = start_task(root, task)
    analysis = state.get("phases", {}).get("analysis", {}).get("artifact")
    acceptance = state.get("phases", {}).get("alignment", {}).get("artifact")
    print("AgentLoop task started.")
    print(f"  task_id: {state.get('task_id')}")
    print("  status: WAITING_FOR_ALIGNMENT")
    print("  artifacts:")
    print(f"    - {analysis}")
    print(f"    - {acceptance}")
    print(f"  next_action: {next_action(state)}")
    return 0


def cmd_approve(root: Path, approved_by: str, task_id: str | None) -> int:
    state = approve_task(root, approved_by=approved_by, task_id=task_id)
    print("AgentLoop alignment approved.")
    print(f"  task_id: {state.get('task_id')}")
    print(f"  approved_by: {approved_by}")
    print("  status: READY_TO_START")
    print(f"  next_action: {next_action(state)}")
    return 0


def cmd_cancel(root: Path, cancelled_by: str, task_id: str | None) -> int:
    state = cancel_task(root, cancelled_by=cancelled_by, task_id=task_id)
    print("AgentLoop task cancelled.")
    print(f"  task_id: {state.get('task_id')}")
    print(f"  cancelled_by: {cancelled_by}")
    print("  status: CANCELLED")
    print(f"  next_action: {next_action(state)}")
    return 0


def cmd_run(root: Path, task_id: str | None, wait: bool) -> int:
    tid = resolve_task_id(root, task_id)
    try:
        with task_lock(root, tid, blocking=wait):
            state = run_task(root, task_id=tid)
    except LockHeld as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("AgentLoop run completed.")
    print(f"  task_id: {state.get('task_id')}")
    print(f"  status: {state.get('status')}")
    print(f"  current_phase: {state.get('current_phase')}")
    print(f"  iteration: {state.get('iteration')}/{state.get('max_iterations')}")
    review = state.get("phases", {}).get("review", {}).get("last_review")
    if review:
        print(f"  review: {review}")
    print(f"  next_action: {next_action(state)}")
    return 0


# ---------- runtime commands (unchanged) ----------


def cmd_runtime_list(root: Path) -> int:
    config = list_runtimes(root)
    print("AgentLoop runtimes")
    print(f"  default_runtime: {config.get('default_runtime', '-')}")
    print("  runtimes:")
    for name, runtime in sorted(config.get("runtimes", {}).items()):
        adapter = runtime.get("adapter", "command") if isinstance(runtime, dict) else "-"
        command = runtime.get("command", "") if isinstance(runtime, dict) else ""
        suffix = f" command={command}" if command else ""
        print(f"    - {name}: adapter={adapter}{suffix}")
    print("  roles:")
    for role, role_config in sorted(config.get("roles", {}).items()):
        runtime = role_config.get("runtime", config.get("default_runtime", "-")) if isinstance(role_config, dict) else "-"
        print(f"    - {role}: {runtime}")
    return 0


def cmd_runtime_detect(root: Path, replace: bool) -> int:
    print_detect_summary(detect_runtimes(root, replace=replace))
    return 0


def cmd_runtime_add_command(root: Path, args: argparse.Namespace) -> int:
    runtime_args = list(args.arg or [])
    if args.args:
        runtime_args.extend(shlex.split(args.args))
    config = add_command_runtime(
        root,
        name=args.name,
        command=args.runtime_executable,
        args=runtime_args,
        stdin_file=args.stdin_file,
        timeout_seconds=args.timeout_seconds,
        set_default=args.set_default,
        replace=args.replace,
    )
    print("Runtime added.")
    print(f"  name: {args.name}")
    print("  adapter: command")
    print(f"  command: {args.runtime_executable}")
    print(f"  args: {runtime_args}")
    if args.stdin_file:
        print(f"  stdin_file: {args.stdin_file}")
    print(f"  default_runtime: {config.get('default_runtime')}")
    return 0


def cmd_runtime_add_preset(root: Path, args: argparse.Namespace) -> int:
    config = add_preset_runtime(
        root,
        preset=args.preset,
        assign_roles=list(args.assign or []),
        assign_all=args.assign_all,
        set_default=args.set_default,
        replace=args.replace,
    )
    print("Runtime preset added.")
    print(f"  preset: {args.preset}")
    print(f"  default_runtime: {config.get('default_runtime')}")
    if args.assign_all:
        print("  assigned: all roles")
    elif args.assign:
        print(f"  assigned: {', '.join(args.assign)}")
    else:
        print("  assigned: -")
    return 0


def cmd_runtime_assign(root: Path, role: str, runtime: str) -> int:
    assign_runtime(root, role, runtime)
    print("Runtime assigned.")
    print(f"  role: {role}")
    print(f"  runtime: {runtime}")
    return 0


def cmd_runtime_assign_all(root: Path, runtime: str, except_roles: list[str]) -> int:
    assign_all_runtime(root, runtime, except_roles=except_roles)
    print("Runtime assigned to roles.")
    print(f"  runtime: {runtime}")
    if except_roles:
        print(f"  except: {', '.join(except_roles)}")
    else:
        print("  except: -")
    return 0


def cmd_runtime_set_default(root: Path, runtime: str) -> int:
    set_default_runtime(root, runtime)
    print("Default runtime updated.")
    print(f"  default_runtime: {runtime}")
    return 0


def cmd_runtime_verify(root: Path, runtime: str, timeout_seconds: int) -> int:
    result = verify_runtime(root, runtime, timeout_seconds=timeout_seconds)
    print("Runtime verified.")
    print(f"  runtime: {runtime}")
    print(f"  exit_code: {result.get('exit_code')}")
    print(f"  stdout_log: {result.get('stdout_log')}")
    print(f"  stderr_log: {result.get('stderr_log')}")
    print("  artifact: .agentloop/artifacts/runtime-verify.txt")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    configure_output_encoding()
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    # Best-effort lazy migration. Skip for commands that need a clean workspace.
    if args.command not in {"init"}:
        try:
            if (root / ".agentloop").exists():
                migrate_workspace(root)
        except Exception:
            pass

    try:
        if args.command == "init":
            return cmd_init(root, detect=args.detect_runtimes, replace_runtimes=args.replace_runtimes)
        if args.command == "status":
            return cmd_status(root, _resolve_task_arg(args))
        if args.command == "tasks":
            if args.tasks_command in {None, "list"}:
                statuses = list(getattr(args, "statuses", []) or [])
                as_json = bool(getattr(args, "as_json", False))
                return cmd_tasks_list(root, statuses, as_json)
            if args.tasks_command == "delete":
                return cmd_tasks_delete(root, args.task_id)
            if args.tasks_command in {"delete-all", "clear"}:
                return cmd_tasks_delete_all(root)
            if args.tasks_command == "unlock":
                return cmd_tasks_unlock(root, args.task_id)
            if args.tasks_command == "migrate":
                return cmd_tasks_migrate(root)
            if args.tasks_command == "approve":
                return cmd_tasks_batch_approve(root, args)
            if args.tasks_command == "cancel":
                return cmd_tasks_batch_cancel(root, args)
            if args.tasks_command == "run":
                return cmd_tasks_batch_run(root, args)
            if args.tasks_command == "config":
                if args.config_command == "show":
                    return cmd_tasks_config_show(root, args.task_id, args.effective)
                if args.config_command == "set":
                    return cmd_tasks_config_set(root, args)
                if args.config_command == "unset":
                    return cmd_tasks_config_unset(root, args)
                if args.config_command == "clear":
                    return cmd_tasks_config_clear(root, args)
        if args.command == "start":
            return cmd_start(root, args.task)
        if args.command == "approve":
            return cmd_approve(root, args.by, _resolve_task_arg(args))
        if args.command == "cancel":
            return cmd_cancel(root, args.by, _resolve_task_arg(args))
        if args.command == "run":
            return cmd_run(root, _resolve_task_arg(args), args.wait)
        if args.command == "runtime":
            if args.runtime_command == "list":
                return cmd_runtime_list(root)
            if args.runtime_command == "detect":
                return cmd_runtime_detect(root, args.replace)
            if args.runtime_command == "add-command":
                return cmd_runtime_add_command(root, args)
            if args.runtime_command == "add-preset":
                return cmd_runtime_add_preset(root, args)
            if args.runtime_command == "assign":
                return cmd_runtime_assign(root, args.role, args.runtime)
            if args.runtime_command == "assign-all":
                return cmd_runtime_assign_all(root, args.runtime, list(args.except_roles or []))
            if args.runtime_command == "set-default":
                return cmd_runtime_set_default(root, args.runtime)
            if args.runtime_command == "verify":
                return cmd_runtime_verify(root, args.runtime, args.timeout_seconds)
    except WorkspaceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
