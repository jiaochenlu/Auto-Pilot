"""Cross-role handoff packages.

Each role writes a structured `handoff/<role>-<NNN>.json` alongside its
primary artifacts. Downstream roles get the most recent handoff(s) injected
into their prompt so context survives a role switch even when the runtime
or session changes. Handoff is the source of truth for cross-session
context; same-role session resume (Phase 2) is an optimization on top.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import utc_now_iso
from .workspace import task_artifact_path, task_artifact_ref


# Ordered chain of roles in the workflow. A downstream role consumes
# handoffs from the closest prior roles in this list.
ROLE_CHAIN: list[str] = [
    "framer",
    "investigator",
    "architect",
    "implementer",
    "tester",
    "reviewer",
    "integrator",
]


HANDOFF_SCHEMA_VERSION = 1


def handoff_dir_ref(task_id: str) -> str:
    return task_artifact_ref(task_id, "handoff/")


def handoff_ref(task_id: str, role: str, turn: int) -> str:
    return task_artifact_ref(task_id, f"handoff/{role}-{turn:03d}.json")


def handoff_path(root: Path, task_id: str, role: str, turn: int) -> Path:
    return task_artifact_path(root, task_id, f"handoff/{role}-{turn:03d}.json")


def next_turn_for_role(state: dict[str, Any], role: str) -> int:
    log = state.get("context_log") or []
    return 1 + sum(1 for entry in log if isinstance(entry, dict) and entry.get("role") == role)


def latest_handoff_for_role(root: Path, state: dict[str, Any], role: str) -> dict[str, Any] | None:
    """Return the most recent handoff payload written by `role` for this task, or None."""
    log = state.get("context_log") or []
    for entry in reversed(log):
        if not isinstance(entry, dict) or entry.get("role") != role:
            continue
        ref = entry.get("handoff_ref")
        if not isinstance(ref, str) or not ref:
            continue
        path = root / ref
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def upstream_roles_for(role: str) -> list[str]:
    """Roles that ran before `role` in the chain, in order."""
    if role not in ROLE_CHAIN:
        return []
    idx = ROLE_CHAIN.index(role)
    return ROLE_CHAIN[:idx]


def collect_upstream_handoffs(root: Path, state: dict[str, Any], role: str) -> list[dict[str, Any]]:
    """Latest handoff per upstream role, in chain order. Missing handoffs are skipped."""
    out: list[dict[str, Any]] = []
    for upstream in upstream_roles_for(role):
        payload = latest_handoff_for_role(root, state, upstream)
        if payload:
            out.append(payload)
    return out


def render_upstream_handoff_block(handoffs: list[dict[str, Any]]) -> str:
    """Markdown block injected into a downstream role's prompt."""
    if not handoffs:
        return ""
    lines: list[str] = ["## Upstream handoff", ""]
    for h in handoffs:
        role = str(h.get("role") or "?")
        turn = h.get("turn")
        header = f"### From `{role}`" + (f" (turn {turn})" if turn else "")
        lines.append(header)
        summary = str(h.get("summary") or "").strip()
        if summary:
            lines.append(summary)
        decisions = h.get("decisions") or []
        if isinstance(decisions, list) and decisions:
            lines.append("")
            lines.append("**Decisions made:**")
            for d in decisions:
                if isinstance(d, dict):
                    what = str(d.get("what") or "").strip()
                    why = str(d.get("why") or "").strip()
                    if what:
                        lines.append(f"- {what}" + (f" — _why:_ {why}" if why else ""))
                elif isinstance(d, str):
                    lines.append(f"- {d}")
        applied = h.get("user_answers_applied") or {}
        if isinstance(applied, dict) and applied:
            lines.append("")
            lines.append("**User answers applied:**")
            for k, v in applied.items():
                lines.append(f"- {k}: {v}")
        concerns = h.get("open_concerns_for_next") or []
        if isinstance(concerns, list) and concerns:
            lines.append("")
            lines.append("**Open concerns flagged for you:**")
            for c in concerns:
                lines.append(f"- {c}")
        pointers = h.get("context_pointers") or []
        if isinstance(pointers, list) and pointers:
            lines.append("")
            lines.append("**Reference files:** " + ", ".join(f"`{p}`" for p in pointers))
        lines.append("")
    lines.append("Read the upstream handoff carefully before producing your output. "
                 "Resolve any flagged concerns or call them out explicitly in your own handoff.")
    lines.append("")
    return "\n".join(lines) + "\n"


def handoff_output_contract_brief(task_id: str, role: str, turn: int) -> str:
    """Short reminder for resume turns where the full schema is already in session context."""
    ref = handoff_ref(task_id, role, turn)
    return (
        "## Handoff contract\n\n"
        f"Write the handoff JSON to `{ref}` using the same schema as turn 1.\n"
    )


def handoff_output_contract(task_id: str, role: str, turn: int) -> str:
    """Prompt fragment instructing the role to produce its handoff JSON."""
    ref = handoff_ref(task_id, role, turn)
    return (
        "## Handoff contract (mandatory)\n\n"
        f"In addition to the artifacts above, you MUST write a JSON handoff package to `{ref}`.\n"
        "This file is what the next role reads. Use exactly this schema:\n\n"
        "```json\n"
        "{\n"
        f"  \"schema_version\": {HANDOFF_SCHEMA_VERSION},\n"
        f"  \"role\": \"{role}\",\n"
        f"  \"turn\": {turn},\n"
        "  \"summary\": \"1-3 sentences: what you did this turn\",\n"
        "  \"decisions\": [\n"
        "    {\"what\": \"...\", \"why\": \"...\", \"alternatives_rejected\": [\"...\"]}\n"
        "  ],\n"
        "  \"user_answers_applied\": {\"Q-id\": \"answer text\"},\n"
        "  \"open_concerns_for_next\": [\"explicit warning or hint for the next role\"],\n"
        "  \"context_pointers\": [\"artifact paths you produced or rely on\"]\n"
        "}\n"
        "```\n\n"
        "- Keep it tight; this is for the next role, not a status report.\n"
        "- Omit fields that don't apply rather than padding them.\n"
        "- This file is required; the workflow will warn if it's missing.\n"
    )


def write_handoff_stub(
    root: Path,
    task_id: str,
    role: str,
    turn: int,
    summary: str,
    *,
    decisions: list[dict[str, Any]] | None = None,
    user_answers_applied: dict[str, str] | None = None,
    open_concerns_for_next: list[str] | None = None,
    context_pointers: list[str] | None = None,
) -> str:
    """Fallback writer used by manual runtime so the chain stays unbroken."""
    payload = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "role": role,
        "turn": turn,
        "summary": summary,
        "decisions": decisions or [],
        "user_answers_applied": user_answers_applied or {},
        "open_concerns_for_next": open_concerns_for_next or [],
        "context_pointers": context_pointers or [],
        "written_at": utc_now_iso(),
        "auto_generated": True,
    }
    path = handoff_path(root, task_id, role, turn)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return handoff_ref(task_id, role, turn)


def append_context_log(
    state: dict[str, Any],
    *,
    role: str,
    turn: int,
    runtime: str | None,
    handoff_ref_value: str | None,
    transcript_ref: str | None = None,
    handoff_present: bool = True,
) -> None:
    log = state.setdefault("context_log", [])
    log.append(
        {
            "role": role,
            "turn": turn,
            "runtime": runtime,
            "handoff_ref": handoff_ref_value,
            "transcript_ref": transcript_ref,
            "handoff_present": handoff_present,
            "at": utc_now_iso(),
        }
    )
