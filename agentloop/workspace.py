"""Workspace file operations for AgentLoop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import default_config, default_state


AGENTLOOP_DIR = ".agentloop"
CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

PROMPT_TEMPLATES = {
    "analysis.md": """# Analyst Prompt\n\nAnalyze the task request and produce `.agentloop/artifacts/analysis.md` and `.agentloop/artifacts/acceptance.md`.\n\nRequired outputs:\n- Task understanding\n- Assumptions\n- Risks\n- Draft acceptance criteria\n""",
    "acceptance.md": """# Acceptance Criteria Prompt\n\nDraft structured acceptance criteria for the current task.\n""",
    "architect.md": """# Architect Prompt\n\nProduce `.agentloop/artifacts/design.md` for the approved task.\n""",
    "implementer.md": """# Implementer Prompt\n\nImplement the approved design while respecting file ownership boundaries.\n""",
    "tester.md": """# Tester Prompt\n\nProduce `.agentloop/artifacts/test-plan.md`, add or update tests, and record test evidence.\n""",
    "reviewer.md": """# Reviewer Prompt\n\nReview the result against acceptance criteria and emit strict JSON to `.agentloop/artifacts/review-001.json`.\n""",
    "integrator.md": """# Integrator Prompt\n\nProduce `.agentloop/artifacts/final-report.md` after the task is approved.\n""",
}


class WorkspaceError(RuntimeError):
    pass


def agentloop_path(root: Path) -> Path:
    return root / AGENTLOOP_DIR


def config_path(root: Path) -> Path:
    return agentloop_path(root) / CONFIG_FILE


def state_path(root: Path) -> Path:
    return agentloop_path(root) / STATE_FILE


def artifact_path(root: Path, name: str) -> Path:
    return agentloop_path(root) / "artifacts" / name


def task_artifact_ref(task_id: str, name: str) -> str:
    return f".agentloop/tasks/{task_id}/artifacts/{name}"


def task_artifact_path(root: Path, task_id: str, name: str) -> Path:
    return root / task_artifact_ref(task_id, name)


def ensure_workspace(root: Path) -> None:
    base = agentloop_path(root)
    for relative in ["prompts", "artifacts", "tasks", "runs", "locks"]:
        (base / relative).mkdir(parents=True, exist_ok=True)


def write_json_if_missing(path: Path, data: dict[str, Any]) -> bool:
    if path.exists():
        return False
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def write_text_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def init_workspace(root: Path) -> dict[str, list[str]]:
    ensure_workspace(root)
    created: list[str] = []
    skipped: list[str] = []

    files: list[tuple[Path, Any, str]] = [
        (config_path(root), default_config(), "json"),
        (state_path(root), default_state(), "json"),
    ]

    for path, data, kind in files:
        did_create = write_json_if_missing(path, data) if kind == "json" else False
        (created if did_create else skipped).append(str(path.relative_to(root)))

    prompts_dir = agentloop_path(root) / "prompts"
    for name, content in PROMPT_TEMPLATES.items():
        path = prompts_dir / name
        did_create = write_text_if_missing(path, content)
        (created if did_create else skipped).append(str(path.relative_to(root)))

    return {"created": created, "skipped": skipped}


def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.exists():
        raise WorkspaceError("AgentLoop is not initialized. Run `agentloop init` first.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Invalid state file: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError(f"Invalid state file: {path}: expected a JSON object")
    return data


def load_config(root: Path) -> dict[str, Any]:
    path = config_path(root)
    if not path.exists():
        raise WorkspaceError("AgentLoop config is missing. Run `agentloop init` first.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Invalid config file: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError(f"Invalid config file: {path}: expected a JSON object")
    return data


def save_state(root: Path, state: dict[str, Any]) -> None:
    task_id = state.get("task_id")
    if isinstance(task_id, str) and task_id:
        write_json(agentloop_path(root) / "tasks" / task_id / "state.json", state)
        # Mirror to legacy global state.json only if this is the current task
        # (or no pointer is set). This keeps backwards compatibility while
        # allowing concurrent non-current tasks to mutate without clobbering.
        pointer_path = state_path(root)
        current = None
        if pointer_path.exists():
            try:
                pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
                if isinstance(pointer, dict):
                    current = pointer.get("task_id")
            except json.JSONDecodeError:
                current = None
        if current is None or current == task_id:
            write_json(pointer_path, state)
    else:
        write_json(state_path(root), state)
