"""Same-role session resume (L1 acceleration).

A session is keyed by (task_id, role, runtime). When a role runs again for
the same task on the same runtime, we pass the prior session_id back to the
CLI via `resume_args` so the runtime can keep its KV cache and conversation
history. If the runtime swaps, the session is invalidated (the new runtime
has no history of the old one) and we cold-start.

Session metadata lives in `state["role_sessions"][role]` and is updated
after every run.
"""

from __future__ import annotations

import re
from typing import Any

from .models import utc_now_iso


def get_role_session(state: dict[str, Any], role: str, runtime_name: str) -> dict[str, Any] | None:
    """Return the prior session entry for (role, runtime), or None.

    A session bound to a different runtime than the one currently configured
    is treated as missing — the new runtime cannot resume the old one's state.
    """
    sessions = state.get("role_sessions") or {}
    entry = sessions.get(role)
    if not isinstance(entry, dict):
        return None
    if entry.get("runtime") != runtime_name:
        return None
    if not entry.get("session_id"):
        return None
    if entry.get("invalidated"):
        return None
    return entry


def update_role_session(
    state: dict[str, Any],
    role: str,
    *,
    session_id: str,
    runtime_name: str,
) -> None:
    sessions = state.setdefault("role_sessions", {})
    existing = sessions.get(role) if isinstance(sessions.get(role), dict) else {}
    sessions[role] = {
        "session_id": session_id,
        "runtime": runtime_name,
        "started_at": existing.get("started_at") or utc_now_iso(),
        "last_used_at": utc_now_iso(),
        "turns": int(existing.get("turns") or 0) + 1,
        "invalidated": False,
    }


def invalidate_role_session(state: dict[str, Any], role: str, reason: str | None = None) -> None:
    sessions = state.get("role_sessions") or {}
    entry = sessions.get(role)
    if isinstance(entry, dict):
        entry["invalidated"] = True
        if reason:
            entry["invalidation_reason"] = reason
        entry["invalidated_at"] = utc_now_iso()


def runtime_supports_resume(runtime_cfg: dict[str, Any]) -> bool:
    return bool(runtime_cfg.get("supports_resume"))


def extract_session_id(runtime_cfg: dict[str, Any], stdout: str, stderr: str) -> str | None:
    """Extract a session id from runtime output using the configured regex.

    The regex should have one capturing group containing the id. If no group
    is defined, the entire match is returned. Returns None if no pattern is
    configured or no match is found.
    """
    pattern = runtime_cfg.get("session_id_regex")
    if not pattern:
        return None
    try:
        compiled = re.compile(pattern)
    except re.error:
        return None
    for text in (stdout, stderr):
        if not text:
            continue
        m = compiled.search(text)
        if not m:
            continue
        if m.groups():
            value = m.group(1)
        else:
            value = m.group(0)
        if value:
            return value.strip()
    return None
