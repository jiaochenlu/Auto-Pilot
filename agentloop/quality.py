"""Quality gate evaluation for AgentLoop review artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .workspace import WorkspaceError


VALID_DECISIONS = {"APPROVED", "CHANGES_REQUIRED", "BLOCKED"}


def load_review(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise WorkspaceError(f"Review artifact is missing: {path}")
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Invalid review JSON: {path}: {exc}") from exc
    if not isinstance(review, dict):
        raise WorkspaceError(f"Invalid review JSON: {path}: expected an object")
    decision = review.get("decision")
    if decision not in VALID_DECISIONS:
        raise WorkspaceError(f"Invalid review decision: {decision}")
    return review


def required_acceptance_passed(state: dict[str, Any], review: dict[str, Any]) -> bool:
    results = {
        item.get("criteria_id"): item.get("status")
        for item in review.get("acceptance_results", [])
        if isinstance(item, dict)
    }
    for criterion in state.get("acceptance_criteria", []):
        if not criterion.get("required", False):
            continue
        status = results.get(criterion.get("id"), criterion.get("status"))
        if status not in {"passed", "waived"}:
            return False
    return True


def tests_passed(review: dict[str, Any]) -> bool:
    for result in review.get("test_results", []):
        if isinstance(result, dict) and result.get("exit_code") != 0:
            return False
    return True


def requires_automated_tests(state: dict[str, Any]) -> bool:
    automated_markers = {"automated_test", "unit_test", "integration_test", "pytest", "unittest", "test"}
    for criterion in state.get("acceptance_criteria", []):
        if not isinstance(criterion, dict) or not criterion.get("required", False):
            continue
        verification = str(criterion.get("verification") or "").strip().lower()
        if verification in automated_markers or "test" in verification or "测试" in verification:
            return True
    return False


def has_executed_passing_test(review: dict[str, Any]) -> bool:
    for result in review.get("test_results", []):
        if isinstance(result, dict) and result.get("exit_code") == 0:
            return True
    return False


def evaluate_gate(state: dict[str, Any], review: dict[str, Any]) -> str:
    decision = review.get("decision")
    if decision == "BLOCKED":
        return "BLOCKED"
    if decision == "CHANGES_REQUIRED":
        return "CHANGES_REQUIRED"

    open_medium_high = int(review.get("open_medium_high_count") or 0)
    if open_medium_high > 0:
        return "CHANGES_REQUIRED"
    if not required_acceptance_passed(state, review):
        return "CHANGES_REQUIRED"
    if not tests_passed(review):
        return "CHANGES_REQUIRED"
    if requires_automated_tests(state) and not has_executed_passing_test(review):
        return "CHANGES_REQUIRED"
    return "APPROVED"
