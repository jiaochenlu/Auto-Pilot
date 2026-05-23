"""Safe bounded readers for AgentLoop UI artifacts and logs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .workspace import WorkspaceError


DEFAULT_LIMIT_BYTES = 64 * 1024


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def resolve_under(base: Path, relative: str | Path) -> Path:
    if isinstance(relative, Path):
        candidate = relative
    else:
        if not relative or "\x00" in relative:
            raise WorkspaceError("Invalid path.")
        candidate = Path(relative)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (base / candidate).resolve()
    resolved_base = base.resolve()
    if not _is_relative_to(resolved, resolved_base):
        raise WorkspaceError("Path escapes allowed directory.")
    return resolved


def bounded_text(path: Path, *, limit_bytes: int = DEFAULT_LIMIT_BYTES) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "missing": not path.exists(),
        "truncated": False,
        "bytes_total": 0,
        "bytes_returned": 0,
        "content": "",
    }
    if not path.exists():
        return payload
    if not path.is_file():
        raise WorkspaceError(f"Path is not a file: {path}")

    size = path.stat().st_size
    payload["bytes_total"] = size
    with path.open("rb") as handle:
        if size > limit_bytes:
            handle.seek(max(size - limit_bytes, 0))
            raw = handle.read(limit_bytes)
            payload["truncated"] = True
        else:
            raw = handle.read()
    text = raw.decode("utf-8", errors="replace")
    payload["bytes_returned"] = len(raw)
    payload["content"] = text
    return payload


def bounded_workspace_file(root: Path, relative: str, *, limit_bytes: int = DEFAULT_LIMIT_BYTES) -> dict[str, Any]:
    path = resolve_under(root, relative)
    payload = bounded_text(path, limit_bytes=limit_bytes)
    payload["path"] = path.resolve().relative_to(root.resolve()).as_posix()
    return payload
