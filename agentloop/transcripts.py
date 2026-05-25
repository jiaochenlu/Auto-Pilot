"""Per-turn transcript capture.

A transcript bundles the prompt, model output (stdout), error stream
(stderr), runtime metadata, and session linkage for one role/turn. It's
written next to the role's primary artifacts so the UI and future
sessions can replay the conversation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import utc_now_iso
from .workspace import task_artifact_path, task_artifact_ref


TRANSCRIPT_SCHEMA_VERSION = 1


def transcript_ref(task_id: str, role: str, turn: int) -> str:
    return task_artifact_ref(task_id, f"transcripts/{role}-{turn:03d}.json")


def transcript_path(root: Path, task_id: str, role: str, turn: int) -> Path:
    return task_artifact_path(root, task_id, f"transcripts/{role}-{turn:03d}.json")


def _read_optional(root: Path, rel: str | None, *, limit_bytes: int = 200_000) -> str | None:
    if not rel:
        return None
    path = root / rel
    if not path.exists():
        return None
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if len(data) > limit_bytes:
        return data[:limit_bytes] + f"\n... [truncated, {len(data) - limit_bytes} bytes omitted]"
    return data


def write_transcript(
    root: Path,
    task_id: str,
    role: str,
    turn: int,
    *,
    runtime: str | None,
    adapter_result: dict[str, Any] | None,
    prompt_ref: str | None = None,
) -> str:
    """Write a transcript file and return its workspace-relative ref."""
    adapter_result = adapter_result or {}
    prompt_text = _read_optional(root, prompt_ref) if prompt_ref else None
    stdout_text = _read_optional(root, adapter_result.get("stdout_log"))
    stderr_text = _read_optional(root, adapter_result.get("stderr_log"))
    payload: dict[str, Any] = {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "task_id": task_id,
        "role": role,
        "turn": turn,
        "runtime": runtime,
        "adapter": adapter_result.get("adapter"),
        "command": adapter_result.get("command"),
        "exit_code": adapter_result.get("exit_code"),
        "duration_ms": adapter_result.get("duration_ms"),
        "session_id": adapter_result.get("session_id"),
        "resumed": adapter_result.get("resumed"),
        "stdout_log": adapter_result.get("stdout_log"),
        "stderr_log": adapter_result.get("stderr_log"),
        "prompt_ref": prompt_ref,
        "prompt": prompt_text,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "written_at": utc_now_iso(),
    }
    path = transcript_path(root, task_id, role, turn)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return transcript_ref(task_id, role, turn)


def load_transcript(root: Path, task_id: str, role: str, turn: int) -> dict[str, Any] | None:
    path = transcript_path(root, task_id, role, turn)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def list_transcripts(root: Path, task_id: str) -> list[dict[str, Any]]:
    """Return transcript metadata (without bodies) sorted by file name."""
    base = task_artifact_path(root, task_id, "transcripts")
    if not base.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        out.append(
            {
                "role": data.get("role"),
                "turn": data.get("turn"),
                "runtime": data.get("runtime"),
                "session_id": data.get("session_id"),
                "resumed": data.get("resumed"),
                "exit_code": data.get("exit_code"),
                "duration_ms": data.get("duration_ms"),
                "written_at": data.get("written_at"),
                "ref": task_artifact_ref(task_id, f"transcripts/{path.name}"),
            }
        )
    return out
