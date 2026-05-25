"""Data model helpers for AgentLoop state and config files.

The first phase intentionally uses standard-library dictionaries instead of
Pydantic so the CLI can run without dependency installation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_MAX_ITERATIONS = 7


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_config() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "default_runtime": "manual",
        "runtimes": {
            "manual": {
                "adapter": "manual",
                "description": "Write prompts to disk and wait for the user to provide artifacts.",
            }
        },
        "roles": {
            "framer": {"runtime": "manual"},
            "investigator": {"runtime": "manual"},
            "architect": {"runtime": "manual"},
            "implementer": {"runtime": "manual"},
            "tester": {"runtime": "manual"},
            "reviewer": {"runtime": "manual"},
            "integrator": {"runtime": "manual"},
        },
        "test_commands": [],
        "max_iterations": DEFAULT_MAX_ITERATIONS,
    }


def default_state() -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": None,
        "title": None,
        "status": "CREATED",
        "current_phase": None,
        "iteration": 0,
        "max_iterations": DEFAULT_MAX_ITERATIONS,
        "requires_human_approval": False,
        "goal": {
            "raw_request": None,
            "problem": None,
            "desired_outcome": None,
            "non_goals": [],
        },
        "acceptance_criteria": [],
        "phases": {
            "framing": {
                "status": "pending",
                "artifact": ".agentloop/artifacts/framing.md",
            },
            "framing_review": {
                "status": "pending",
                "artifact": ".agentloop/artifacts/framing.md",
            },
            "investigation": {
                "status": "pending",
                "artifact": ".agentloop/artifacts/dossier.md",
            },
            "proposal": {
                "status": "pending",
                "artifact": ".agentloop/artifacts/proposal.md",
            },
            "alignment": {
                "status": "pending",
                "approved_by": None,
                "approved_at": None,
            },
            "test_authoring": {
                "status": "pending",
                "artifact": ".agentloop/artifacts/test-plan.md",
            },
            "implementation": {"status": "pending"},
            "testing": {
                "status": "pending",
                "artifact": ".agentloop/artifacts/test-plan.md",
            },
            "review": {
                "status": "pending",
                "last_review": None,
            },
        },
        "agents": [],
        "context_log": [],
        "role_sessions": {},
        "created_at": now,
        "updated_at": now,
    }


def next_action(state: dict[str, Any]) -> str:
    status = state.get("status")
    phases = state.get("phases", {}) if isinstance(state.get("phases"), dict) else {}
    framing_ref = phases.get("framing", {}).get("artifact", ".agentloop/artifacts/framing.md")
    acceptance_ref = ".agentloop/artifacts/acceptance.md"
    final_ref = ".agentloop/artifacts/final-report.md"
    task_id = state.get("task_id")
    if isinstance(task_id, str) and task_id:
        final_ref = f".agentloop/tasks/{task_id}/artifacts/final-report.md"
    if status == "CREATED":
        return "Run `agentloop start \"<task>\"` to draft the framing and open questions."
    if status == "FRAMING_REVIEW":
        return f"Answer the open questions in `{framing_ref}`, then click \"Start research\"."
    if status in {"INVESTIGATING", "DESIGNING"}:
        return "Research in progress — wait for the dossier, proposal, acceptance, and test plan."
    if status == "WAITING_FOR_ALIGNMENT":
        return f"Review the design package and acceptance (`{acceptance_ref}`), then run `agentloop approve`."
    if status == "READY_TO_START":
        return "Run `agentloop run` to start the implementation/testing/review loop."
    if status in {"IMPLEMENTING_AND_TESTING", "REVIEWING"}:
        return "Run `agentloop run` or wait for the active phase to finish."
    if status == "WAITING_FOR_HUMAN":
        return "Review the latest artifact or review report, then run the appropriate resume command."
    if status == "DONE":
        return f"Task is complete. Review `{final_ref}`."
    if status == "BLOCKED":
        return "Task is blocked. Inspect the current task artifact directory and update the task manually."
    if status == "CANCELLED":
        return "Task is cancelled."
    return "No next action is known for this state."
