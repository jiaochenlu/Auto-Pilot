"""Chat module: independent conversational sessions with a chosen runtime.

Storage layout (per workspace):
  .agentloop/chats/{chat_id}/state.json     # chat metadata + messages
  .agentloop/chats/{chat_id}/prompts/NNN.md # per-turn prompt sent to runtime
  .agentloop/chats/{chat_id}/runs/NNN.{stdout,stderr}.log  # raw runtime output
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workspace import WorkspaceError, agentloop_path, write_json


CHAT_SCHEMA_VERSION = 1


def chats_dir(root: Path) -> Path:
    return agentloop_path(root) / "chats"


def chat_dir(root: Path, chat_id: str) -> Path:
    if not chat_id or chat_id in {".", ".."} or any(sep in chat_id for sep in ["/", "\\"]):
        raise WorkspaceError(f"Invalid chat_id: {chat_id}")
    base = chats_dir(root)
    target = (base / chat_id).resolve()
    if not str(target).lower().startswith(str(base.resolve()).lower()):
        raise WorkspaceError(f"Invalid chat path: {chat_id}")
    return target


def chat_state_path(root: Path, chat_id: str) -> Path:
    return chat_dir(root, chat_id) / "state.json"


def chat_prompt_path(root: Path, chat_id: str, turn: int) -> Path:
    return chat_dir(root, chat_id) / "prompts" / f"{turn:03d}.md"


def chat_run_log_paths(root: Path, chat_id: str, turn: int) -> tuple[Path, Path]:
    base = chat_dir(root, chat_id) / "runs"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{turn:03d}.stdout.log", base / f"{turn:03d}.stderr.log"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_chat_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"chat-{ts}-{uuid.uuid4().hex[:6]}"


def new_message_id() -> str:
    return f"msg-{uuid.uuid4().hex[:10]}"


def default_chat_state(chat_id: str, *, title: str, runtime: str,
                       system_prompt: str | None = None,
                       working_dir: str | None = None) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "schema_version": CHAT_SCHEMA_VERSION,
        "chat_id": chat_id,
        "title": title,
        "runtime": runtime,
        "system_prompt": system_prompt or "",
        "working_dir": working_dir or "",
        "session_id": None,
        "messages": [],
        "status": "idle",
        "last_error": None,
        "compact_summary": "",
        "compact_up_to_message_id": None,
        "compact_history": [],
        "created_at": now,
        "updated_at": now,
    }


def list_chat_ids(root: Path) -> list[str]:
    base = chats_dir(root)
    if not base.exists():
        return []
    return sorted(item.name for item in base.iterdir() if item.is_dir())


def load_chat_state(root: Path, chat_id: str) -> dict[str, Any]:
    path = chat_state_path(root, chat_id)
    if not path.exists():
        raise WorkspaceError(f"Chat state not found: {chat_id}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Invalid chat state: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError(f"Invalid chat state: {path}: expected object")
    if not isinstance(data.get("messages"), list):
        data["messages"] = []
    data.setdefault("compact_summary", "")
    data.setdefault("compact_up_to_message_id", None)
    if not isinstance(data.get("compact_history"), list):
        data["compact_history"] = []
    return data


def save_chat_state(root: Path, chat_id: str, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now_iso()
    write_json(chat_state_path(root, chat_id), state)


def create_chat(root: Path, *, title: str | None, runtime: str,
                system_prompt: str | None = None,
                working_dir: str | None = None) -> dict[str, Any]:
    chat_id = new_chat_id()
    chat_dir(root, chat_id).mkdir(parents=True, exist_ok=True)
    state = default_chat_state(
        chat_id,
        title=(title or "New chat").strip()[:120] or "New chat",
        runtime=runtime,
        system_prompt=system_prompt,
        working_dir=working_dir,
    )
    save_chat_state(root, chat_id, state)
    return state


def delete_chat(root: Path, chat_id: str) -> None:
    target = chat_dir(root, chat_id)
    if not target.exists():
        return

    def _force_writable(path: Path) -> None:
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        except OSError:
            pass

    def _onerror(func, path, exc_info):
        # OneDrive / Windows often marks files read-only. Clear the bit and retry.
        _force_writable(Path(path))
        try:
            func(path)
        except Exception:
            raise

    # Pre-clear read-only bits on the dir and its contents.
    _force_writable(target)
    for sub in target.rglob("*"):
        _force_writable(sub)

    try:
        shutil.rmtree(target, onerror=_onerror)
    except PermissionError as exc:
        raise WorkspaceError(
            f"Cannot delete chat directory (permission denied — close any process "
            f"holding files in {target}, or pause OneDrive sync, then retry)."
        ) from exc
    except OSError as exc:
        raise WorkspaceError(f"Failed to delete chat directory: {exc}") from exc


def append_message(state: dict[str, Any], role: str, content: str,
                   *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    msg = {
        "id": new_message_id(),
        "role": role,
        "content": content,
        "ts": utc_now_iso(),
    }
    if meta:
        msg["meta"] = meta
    state["messages"].append(msg)
    return msg


def find_message_index(state: dict[str, Any], message_id: str) -> int:
    for i, msg in enumerate(state.get("messages") or []):
        if msg.get("id") == message_id:
            return i
    raise WorkspaceError(f"Message not found: {message_id}")


def truncate_after(state: dict[str, Any], index: int) -> None:
    state["messages"] = state["messages"][: index + 1]


def message_preview(state: dict[str, Any], limit: int = 80) -> str:
    msgs = state.get("messages") or []
    if not msgs:
        return ""
    last = msgs[-1]
    text = str(last.get("content") or "").replace("\n", " ").strip()
    return text[:limit]


DEFAULT_TITLES = {"", "new chat", "untitled chat"}


def _is_default_title(title: str) -> bool:
    t = (title or "").strip().lower()
    if t in DEFAULT_TITLES:
        return True
    # Treat "new chat (anything)" — produced when switching runtimes — as
    # still a default placeholder, so the first real message can rename it.
    if t.startswith("new chat (") and t.endswith(")"):
        return True
    return False


def derive_title_from_text(text: str, *, max_len: int = 32) -> str:
    """Make a short chat title from a user message. First non-empty line,
    collapse whitespace, trim trailing punctuation, then truncate."""

    if not text:
        return "New chat"
    first_line = ""
    for line in text.splitlines():
        line = line.strip()
        if line:
            first_line = line
            break
    if not first_line:
        return "New chat"
    cleaned = " ".join(first_line.split())
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip() + "…"
    else:
        cleaned = cleaned.rstrip(" .,;:!?。，；：！？")
    return cleaned or "New chat"


def maybe_autotitle(state: dict[str, Any]) -> bool:
    """If the chat still has a default title and exactly one user message,
    derive a short title from it. Returns True if state was modified."""

    current = (state.get("title") or "").strip().lower()
    if not _is_default_title(current):
        return False
    user_msgs = [m for m in (state.get("messages") or []) if m.get("role") == "user"]
    if len(user_msgs) != 1:
        return False
    title = derive_title_from_text(str(user_msgs[0].get("content") or ""))
    if title == state.get("title"):
        return False
    state["title"] = title
    return True


def apply_compact(state: dict[str, Any], summary: str, up_to_message_id: str,
                  runtime_name: str | None) -> None:
    """Record a compaction: messages up to and including up_to_message_id are
    represented by `summary` when building the next runtime prompt. Raw
    messages stay in state for UI display."""

    prior = state.get("compact_history") or []
    prior.append({
        "summary": state.get("compact_summary") or "",
        "up_to_message_id": state.get("compact_up_to_message_id"),
        "runtime": runtime_name,
        "ts": utc_now_iso(),
    }) if state.get("compact_summary") else None
    state["compact_history"] = prior
    state["compact_summary"] = summary.strip()
    state["compact_up_to_message_id"] = up_to_message_id
