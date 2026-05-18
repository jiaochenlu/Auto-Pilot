"""Runtime adapters for executing AgentLoop roles."""

from __future__ import annotations

import subprocess
import time
import os
from pathlib import Path
from typing import Any

from .workspace import WorkspaceError


class AdapterResult(dict):
    """Dictionary result for adapter execution."""


def relpath(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def render_args(args: list[str], values: dict[str, str]) -> list[str]:
    rendered: list[str] = []
    for arg in args:
        value = arg
        for key, replacement in values.items():
            value = value.replace("{" + key + "}", replacement)
        rendered.append(value)
    return rendered


def role_prompt_path(root: Path, role: str) -> Path:
    return root / ".agentloop" / "prompts" / f"{role}.md"


def role_log_paths(root: Path, iteration: int, role: str, task_id: str | None = None) -> tuple[Path, Path]:
    base = root / ".agentloop" / "runs"
    if task_id:
        run_dir = base / task_id / f"{iteration:03d}"
    else:
        run_dir = base / f"{iteration:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir / f"{role}.stdout.log", run_dir / f"{role}.stderr.log"


def runtime_for_role(config: dict[str, Any], role: str) -> tuple[str, dict[str, Any]]:
    role_config = config.get("roles", {}).get(role, {})
    runtime_name = role_config.get("runtime") or config.get("default_runtime") or "manual"
    runtime = config.get("runtimes", {}).get(runtime_name)
    if not isinstance(runtime, dict):
        raise WorkspaceError(f"Runtime is not configured for role {role}: {runtime_name}")
    return runtime_name, runtime


def run_role(
    root: Path,
    config: dict[str, Any],
    role: str,
    iteration: int,
    required_artifacts: list[str],
    task_id: str | None = None,
) -> AdapterResult:
    runtime_name, runtime = runtime_for_role(config, role)
    adapter = runtime.get("adapter", "command")
    if adapter == "manual":
        return run_manual_role(root, runtime_name, role, iteration, required_artifacts, task_id)
    if adapter == "command":
        return run_command_role(root, runtime_name, runtime, role, iteration, required_artifacts, task_id)
    raise WorkspaceError(f"Unsupported adapter for runtime {runtime_name}: {adapter}")


def run_manual_role(
    root: Path,
    runtime_name: str,
    role: str,
    iteration: int,
    required_artifacts: list[str],
    task_id: str | None = None,
) -> AdapterResult:
    stdout_log, stderr_log = role_log_paths(root, iteration, role, task_id)
    prompt_path = role_prompt_path(root, role)
    stdout_log.write_text(
        f"Manual runtime selected for role: {role}\n"
        f"Prompt file: {relpath(prompt_path, root)}\n"
        "Workflow generated required artifacts locally.\n",
        encoding="utf-8",
    )
    stderr_log.write_text("", encoding="utf-8")
    return AdapterResult(
        role=role,
        runtime=runtime_name,
        adapter="manual",
        command=None,
        exit_code=0,
        stdout_log=relpath(stdout_log, root),
        stderr_log=relpath(stderr_log, root),
        artifacts=required_artifacts,
    )


def run_command_role(
    root: Path,
    runtime_name: str,
    runtime: dict[str, Any],
    role: str,
    iteration: int,
    required_artifacts: list[str],
    task_id: str | None = None,
) -> AdapterResult:
    command = runtime.get("command")
    if not command:
        raise WorkspaceError(f"Command runtime {runtime_name} is missing `command`.")

    stdout_log, stderr_log = role_log_paths(root, iteration, role, task_id)
    prompt_path = role_prompt_path(root, role)
    values = {
        "cwd": str(root),
        "role": role,
        "iteration": str(iteration),
        "prompt_file": str(prompt_path),
    }
    args = render_args(list(runtime.get("args") or []), values)
    timeout = runtime.get("timeout_seconds")
    stdin_text = None
    stdin_file = runtime.get("stdin_file")
    if stdin_file:
        stdin_path = Path(render_args([str(stdin_file)], values)[0])
        if not stdin_path.is_absolute():
            stdin_path = root / stdin_path
        stdin_text = stdin_path.read_text(encoding="utf-8")

    started = time.monotonic()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    try:
        completed = subprocess.run(
            [command, *args],
            cwd=root,
            env=env,
            input=stdin_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        stderr_log.write_text(str(exc), encoding="utf-8")
        raise WorkspaceError(f"Runtime command not found for {runtime_name}: {command}") from exc
    except subprocess.TimeoutExpired as exc:
        stderr_log.write_text(str(exc), encoding="utf-8")
        raise WorkspaceError(f"Role {role} timed out after {timeout} seconds. See {relpath(stderr_log, root)}") from exc
    duration_ms = int((time.monotonic() - started) * 1000)
    stdout_log.write_text(completed.stdout, encoding="utf-8")
    stderr_log.write_text(completed.stderr, encoding="utf-8")

    missing = [artifact for artifact in required_artifacts if not (root / artifact).exists()]
    if completed.returncode != 0:
        raise WorkspaceError(f"Role {role} failed with exit code {completed.returncode}. See {relpath(stderr_log, root)}")
    if missing:
        raise WorkspaceError(f"Role {role} did not produce required artifacts: {', '.join(missing)}")

    return AdapterResult(
        role=role,
        runtime=runtime_name,
        adapter="command",
        command=" ".join([command, *args]),
        exit_code=completed.returncode,
        duration_ms=duration_ms,
        stdout_log=relpath(stdout_log, root),
        stderr_log=relpath(stderr_log, root),
        artifacts=required_artifacts,
    )
