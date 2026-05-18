"""Cross-platform per-task file locks for AgentLoop."""

from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .workspace import WorkspaceError, agentloop_path


class LockHeld(WorkspaceError):
    """Raised when a non-blocking lock acquire fails because another holder owns it."""


def locks_dir(root: Path) -> Path:
    path = agentloop_path(root) / "locks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def lock_path(root: Path, task_id: str) -> Path:
    return locks_dir(root) / f"{task_id}.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return bool(ok) and exit_code.value == 259  # STILL_ACTIVE
        except OSError:
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_lock_payload(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _format_held_message(task_id: str, payload: dict) -> str:
    pid = payload.get("pid", "?")
    started_at = payload.get("started_at", "?")
    host = payload.get("host", "?")
    return f"task {task_id} is locked by pid {pid} on {host} since {started_at}"


@contextmanager
def task_lock(
    root: Path,
    task_id: str,
    *,
    blocking: bool = False,
    poll_interval: float = 0.25,
    timeout_seconds: float | None = None,
    stale_after_seconds: int | None = 3600,
) -> Iterator[Path]:
    """Acquire a per-task lock. Raises LockHeld in non-blocking mode if held."""

    if not task_id:
        raise WorkspaceError("task_lock requires a task_id")

    path = lock_path(root, task_id)
    started_wait = time.monotonic()
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            payload = _read_lock_payload(path)
            holder_pid = payload.get("pid")
            if isinstance(holder_pid, int) and not _pid_alive(holder_pid):
                if stale_after_seconds is not None:
                    try:
                        path.unlink()
                        continue
                    except OSError:
                        pass
            if not blocking:
                raise LockHeld(_format_held_message(task_id, payload))
            if timeout_seconds is not None and time.monotonic() - started_wait > timeout_seconds:
                raise LockHeld(_format_held_message(task_id, payload))
            time.sleep(poll_interval)

    payload = {
        "pid": os.getpid(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": socket.gethostname(),
        "task_id": task_id,
    }
    try:
        os.write(fd, json.dumps(payload).encode("utf-8"))
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)

    try:
        yield path
    finally:
        try:
            path.unlink()
        except OSError:
            pass
