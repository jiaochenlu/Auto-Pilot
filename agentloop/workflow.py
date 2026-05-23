"""Workflow operations for AgentLoop phases."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .adapters import run_role, runtime_for_role
from .models import default_state, utc_now_iso
from .quality import evaluate_gate, load_review
from .runner import run_test_commands
from .workspace import (
    WorkspaceError,
    agentloop_path,
    load_config,
    load_state,
    save_state,
    task_artifact_path,
    task_artifact_ref,
    write_text,
)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:48] or "task"


def create_task_id(raw_request: str) -> str:
    compact_time = utc_now_iso().replace("-", "").replace(":", "").split("+")[0].replace("T", "-")
    return f"{compact_time}-{slugify(raw_request)}"


def draft_analysis(raw_request: str) -> str:
    fragments = requirement_fragments(raw_request)
    requirement_lines = "\n".join(f"- {fragment}" for fragment in fragments)
    return f"""# Task Analysis

## Raw Request

{raw_request}

## Current Understanding

The requester wants this specific outcome delivered:

{requirement_lines}

## Assumptions

- The implementation should stay inside the current workspace.
- The result should satisfy the task-specific acceptance criteria in `acceptance.md`.
- Execution should not start until the requester approves this analysis and the acceptance criteria.

## Risks

- The request may need more detail about exact files, visual style, or verification commands.
- Some acceptance criteria may need manual review if no automated test can verify them.
- If the requester disagrees with these criteria, they should revise the task before approval.

## Open Questions

- None. The current request is specific enough to proceed with conservative assumptions.
"""


def draft_analysis_questions(raw_request: str) -> list[dict[str, Any]]:
    lower = raw_request.lower()
    questions: list[dict[str, Any]] = []
    if any(token in lower for token in ["performance", "slow", "too slow", "性能", "太慢"]):
        questions.append(
            {
                "id": "Q-1",
                "question": "Is there a specific performance target, or should AgentLoop define a conservative benchmark from the current code and input size?",
                "blocking": False,
                "reason": "A target improves precision, but the agent can choose a reasonable regression benchmark if unanswered.",
                "answer": None,
            }
        )
    if not re.search(r"[\w./\\-]+\.(py|js|ts|tsx|jsx|json|md|html|css)\b", raw_request):
        questions.append(
            {
                "id": "Q-2",
                "question": "Which files or area of the codebase should AgentLoop inspect first?",
                "blocking": True,
                "reason": "The request does not name a concrete file or subsystem, so implementation scope may be ambiguous.",
                "answer": None,
            }
        )
    return questions


def append_analysis_answers(analysis: str, questions: list[dict[str, Any]]) -> str:
    if not questions:
        return analysis
    lines = [analysis.rstrip(), "", "## User Answers", ""]
    for item in questions:
        answer = str(item.get("answer") or "").strip() or "No answer provided; proceed with documented assumptions."
        lines.append(f"- {item.get('id')}: {item.get('question')}")
        lines.append(f"  Answer: {answer}")
    return "\n".join(lines) + "\n"


def requirement_fragments(raw_request: str) -> list[str]:
    normalized = re.sub(r"[\r\n]+", " ", raw_request.strip())
    parts = re.split(r"[;；。.!?？]+|要求[:：]", normalized)
    fragments: list[str] = []
    for part in parts:
        fragment = part.strip(" ，,、")
        if len(fragment) >= 4 and fragment not in fragments:
            fragments.append(fragment)
    return fragments or [raw_request.strip()]


def draft_custom_acceptance_items(raw_request: str, analysis_ref: str, acceptance_ref: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, fragment in enumerate(requirement_fragments(raw_request), start=1):
        lower = fragment.lower()
        automated_tokens = [
            "test",
            "tests",
            "unittest",
            "pytest",
            "bug",
            "fix",
            "regression",
            "performance",
            "slow",
            "too slow",
            "timeout",
            "单元测试",
            "测试",
            "缺陷",
            "修复",
            "回归",
            "性能",
            "太慢",
            "超时",
        ]
        verification = "automated_test" if any(token in lower for token in automated_tokens) else "functional_review"
        items.append(
            {
                "id": f"AC-{index}",
                "description": fragment,
                "verification": verification,
                "required": True,
                "status": "pending",
                "evidence": acceptance_ref if verification == "functional_review" else "configured test command output",
            }
        )
    items.append(
        {
            "id": f"AC-{len(items) + 1}",
            "description": "Requester reviews and approves the task-specific analysis and acceptance criteria before execution starts.",
            "verification": "human_review",
            "required": True,
            "status": "pending",
            "evidence": analysis_ref,
        }
    )
    return items


def task_id_or_error(state: dict[str, Any]) -> str:
    task_id = state.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise WorkspaceError("Current task does not have a task_id.")
    return task_id


def artifact_ref(state: dict[str, Any], name: str) -> str:
    return task_artifact_ref(task_id_or_error(state), name)


def artifact_file(root: Path, state: dict[str, Any], name: str) -> Path:
    return task_artifact_path(root, task_id_or_error(state), name)


def write_role_prompt(root: Path, role: str, content: str) -> None:
    write_text(agentloop_path(root) / "prompts" / f"{role}.md", content)


def prepare_analyst_prompt(root: Path, state: dict[str, Any]) -> None:
    request = state.get("goal", {}).get("raw_request") or state.get("title") or "Untitled task"
    analysis_ref = artifact_ref(state, "analysis.md")
    acceptance_ref = artifact_ref(state, "acceptance.md")
    acceptance_json_ref = artifact_ref(state, "acceptance.json")
    write_role_prompt(
        root,
        "analyst",
        "# Analyst Prompt\n\n"
        f"Task request:\n{request}\n\n"
        "Analyze this specific task. Do not use generic AgentLoop acceptance criteria unless they are directly required by the task.\n\n"
        "Required outputs:\n"
        f"- Write task-specific analysis to `{analysis_ref}`. Include goal, non-goals, assumptions, risks, and open questions.\n"
        "- Include a `Verification Plan` section in the analysis. For bug, regression, performance, or code-change tasks, name the focused tests or test files that should prove the fix.\n"
        f"- Write human-readable task-specific acceptance criteria to `{acceptance_ref}`.\n"
        f"- Write structured acceptance criteria JSON to `{acceptance_json_ref}`.\n\n"
        "The JSON must be an object with `acceptance_criteria`, an array of objects containing: "
        "id, description, verification, required, status, evidence. Use status `pending`.\n"
        "For bug, regression, performance, slow, timeout, or code-change tasks, include at least one required "
        "criterion with verification `automated_test`; its evidence should name the expected regression test file or command.\n"
        "Stop after producing these files; execution starts only after requester approval.\n",
    )


def prepare_role_prompt(
    root: Path,
    state: dict[str, Any],
    role: str,
    iteration: int,
    review_name: str | None = None,
    mode: str | None = None,
) -> None:
    request = state.get("goal", {}).get("raw_request") or state.get("title") or "Untitled task"
    design_ref = artifact_ref(state, "design.md")
    test_plan_ref = artifact_ref(state, "test-plan.md")
    final_ref = artifact_ref(state, "final-report.md")
    review_ref = artifact_ref(state, review_name or f"review-{iteration:03d}.json")
    artifact_dir_ref = task_artifact_ref(task_id_or_error(state), "")

    common = (
        f"Task: {request}\n"
        f"Iteration: {iteration}\n"
        f"Task artifact directory: `{artifact_dir_ref}`\n"
        "Use paths exactly as written. Do not write task artifacts to `.agentloop/artifacts/`.\n"
    )
    tester_instruction = (
        f"Produce the test plan and evidence at `{test_plan_ref}`. Add or update tests as needed.\n"
    )
    if mode == "pre_implementation":
        tester_instruction = (
            f"Before implementation, create or update focused regression tests for the approved task and write the plan at `{test_plan_ref}`.\n"
            "The tests should fail against the current buggy or slow behavior when feasible, and pass after the implementation fix.\n"
            "Include exact test files, commands, expected signals, and measurable acceptance thresholds when the task implies performance.\n"
            "Do not implement the production fix in this tester step.\n"
        )
    elif mode == "post_implementation":
        tester_instruction = (
            f"After implementation, run the relevant focused tests and update `{test_plan_ref}` with evidence.\n"
            "Record commands, exit codes, important output, timing evidence for performance tasks, and any remaining gaps.\n"
        )

    prompts = {
        "architect": (
            "# Architect Prompt\n\n"
            f"{common}\n"
            f"Produce the design document at `{design_ref}`.\n"
        ),
        "implementer": (
            "# Implementer Prompt\n\n"
            f"{common}\n"
            "Implement the approved task in the workspace. Keep changes scoped to the request.\n"
        ),
        "tester": (
            "# Tester Prompt\n\n"
            f"{common}\n"
            f"{tester_instruction}"
        ),
        "reviewer": (
            "# Reviewer Prompt\n\n"
            f"{common}\n"
            f"Review the result against acceptance criteria and write strict JSON to `{review_ref}`.\n"
            "The JSON object must include: decision, summary, open_medium_high_count, comments, "
            "acceptance_results, and test_results. Use decision APPROVED, CHANGES_REQUIRED, or BLOCKED.\n"
            "Do not use APPROVED if any required automated/unit/test acceptance criterion lacks an executed "
            "test result with exit_code 0. If a test could not run, report CHANGES_REQUIRED or BLOCKED and "
            "include the reason in comments and test_results.\n"
            "Do not use APPROVED for bug, regression, performance, slow, or timeout tasks unless the work added "
            "or updated a focused regression/performance test and the review records passing evidence for it.\n"
        ),
        "integrator": (
            "# Integrator Prompt\n\n"
            f"{common}\n"
            f"Produce the final report at `{final_ref}` after the task is approved.\n"
        ),
    }
    if role in prompts:
        write_role_prompt(root, role, prompts[role])


def draft_acceptance(raw_request: str, criteria: list[dict[str, Any]], analysis_ref: str) -> str:
    rows = "\n".join(
        "| {id} | {required} | {verification} | {description} | {status} | {evidence} |".format(
            id=item.get("id"),
            required="yes" if item.get("required", True) else "no",
            verification=item.get("verification", "review"),
            description=str(item.get("description", "")).replace("|", "\\|"),
            status=item.get("status", "pending"),
            evidence=item.get("evidence", ""),
        )
        for item in criteria
    )
    return f"""# Acceptance Criteria

## Task

{raw_request}

## Draft Criteria

| ID | Required | Verification | Criterion | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
{rows}

## Approval Instruction

Review this file and `{analysis_ref}`. If the scope is correct, run:

```powershell
python -m agentloop approve
```
"""


def draft_design(state: dict[str, Any], iteration: int) -> str:
    request = state.get("goal", {}).get("raw_request") or state.get("title") or "Untitled task"
    artifact_dir_ref = task_artifact_ref(task_id_or_error(state), "")
    return f"""# Design

## Task

{request}

## Iteration

{iteration}

## Approach

AgentLoop will keep orchestration logic local and agent-agnostic. The workflow engine owns task state, artifacts, review gate decisions, and bounded iteration. Coding agents are replaceable runtimes connected through prompt files, artifacts, logs, and structured JSON outputs.

## Runtime Boundary

- Core workflow code must not import or depend on Codex, Claude Code, Copilot, or any other specific coding agent.
- Runtime configuration selects which external agent handles each role.
- The `manual` runtime remains valid for environments where an agent cannot be invoked directly.

## Files And Ownership

- `agentloop/workflow.py`: workflow state transitions.
- `agentloop/quality.py`: review JSON parsing and gate decisions.
- `agentloop/runner.py`: local command execution for tests.
- `{artifact_dir_ref}`: durable workflow artifacts for this task.

## Test Strategy

- Unit tests cover CLI state transitions and artifact generation.
- Configured test commands are run during `agentloop run` when present.
- Review JSON records test evidence and acceptance results.
"""


def draft_test_plan(state: dict[str, Any], test_results: list[dict[str, Any]]) -> str:
    commands = test_results or []
    command_lines = "\n".join(
        f"- `{item['command']}` -> exit {item['exit_code']} ({item['log']})" for item in commands
    ) or "- No test commands configured."
    return f"""# Test Plan

## Scope

Validate the AgentLoop local workflow through state files, artifacts, and command behavior.

## Checks

- `agentloop start` creates analysis and acceptance artifacts.
- `agentloop approve` moves the task to `READY_TO_START`.
- `agentloop run` creates design, test-plan, review, and final-report artifacts.
- Review JSON can be parsed and evaluated by the quality gate.

## Test Command Results

{command_lines}
"""


def manual_review(state: dict[str, Any], test_results: list[dict[str, Any]]) -> dict[str, Any]:
    test_failure = any(item.get("exit_code") not in {0, None} for item in test_results)
    acceptance_results = []
    for criterion in state.get("acceptance_criteria", []):
        status = criterion.get("status")
        if criterion.get("id") in {"AC-1", "AC-2", "AC-3", "AC-4"} and not test_failure:
            status = "passed"
        acceptance_results.append(
            {
                "criteria_id": criterion.get("id"),
                "status": status or "pending",
                "evidence": criterion.get("evidence"),
            }
        )

    if test_failure:
        return {
            "decision": "CHANGES_REQUIRED",
            "summary": "One or more configured test commands failed.",
            "open_medium_high_count": 1,
            "comments": [
                {
                    "id": "R-1",
                    "severity": "high",
                    "area": "tests",
                    "text": "Configured tests must pass before approval.",
                    "required_action": "Fix failing tests and rerun `agentloop run`.",
                    "status": "open",
                }
            ],
            "acceptance_results": acceptance_results,
            "test_results": test_results,
        }

    return {
        "decision": "APPROVED",
        "summary": "Manual runtime generated required Phase 3 artifacts and no configured tests failed.",
        "open_medium_high_count": 0,
        "comments": [],
        "acceptance_results": acceptance_results,
        "test_results": test_results,
    }


def draft_final_report(state: dict[str, Any], review: dict[str, Any]) -> str:
    review_artifact = state.get("phases", {}).get("review", {}).get("last_review") or artifact_ref(state, "review-001.json")
    return f"""# Final Report

## Task

{state.get('title')}

## Result

{review.get('decision')}

## Summary

{review.get('summary')}

## Artifacts

- `{artifact_ref(state, "analysis.md")}`
- `{artifact_ref(state, "acceptance.md")}`
- `{artifact_ref(state, "design.md")}`
- `{artifact_ref(state, "test-plan.md")}`
- `{review_artifact}`

## Residual Risk

- The MVP still uses the manual runtime; real coding agent adapters are configured in later phases.
"""


def role_uses_manual(config: dict[str, Any], role: str) -> bool:
    _, runtime = runtime_for_role(config, role)
    return runtime.get("adapter", "command") == "manual"


def record_agent_result(state: dict[str, Any], result: dict[str, Any]) -> None:
    state.setdefault("agents", []).append(result)


def load_acceptance_criteria(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Invalid acceptance criteria JSON: {path}: {exc}") from exc
    criteria = data.get("acceptance_criteria") if isinstance(data, dict) else None
    if not isinstance(criteria, list) or not criteria:
        raise WorkspaceError(f"Invalid acceptance criteria JSON: {path}: expected non-empty acceptance_criteria list")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(criteria, start=1):
        if not isinstance(item, dict):
            raise WorkspaceError(f"Invalid acceptance criterion at index {index}: expected object")
        description = str(item.get("description") or "").strip()
        if not description:
            raise WorkspaceError(f"Invalid acceptance criterion at index {index}: missing description")
        normalized.append(
            {
                "id": str(item.get("id") or f"AC-{index}"),
                "description": description,
                "verification": str(item.get("verification") or "review"),
                "required": bool(item.get("required", True)),
                "status": str(item.get("status") or "pending"),
                "evidence": str(item.get("evidence") or ""),
            }
        )
    return normalized


def start_task(
    root: Path,
    raw_request: str,
    config_override: dict[str, Any] | None = None,
    require_analysis_review: bool = False,
    run_analyst: bool = True,
) -> dict[str, Any]:
    from .tasks import effective_config, save_task_config, set_current_task_id

    request = raw_request.strip()
    if not request:
        raise WorkspaceError("Task request cannot be empty.")

    task_id = create_task_id(request)
    now = utc_now_iso()
    state = default_state()
    state["task_id"] = task_id
    if config_override:
        save_task_config(root, task_id, config_override)
    config = effective_config(root, task_id)
    analysis_ref = task_artifact_ref(task_id, "analysis.md")
    acceptance_ref = task_artifact_ref(task_id, "acceptance.md")
    acceptance_json_ref = task_artifact_ref(task_id, "acceptance.json")
    state["title"] = request[:80]
    state["status"] = "WAITING_FOR_ANALYSIS_REVIEW" if require_analysis_review else "WAITING_FOR_ALIGNMENT"
    state["current_phase"] = "analysis_review" if require_analysis_review else "alignment"
    state["iteration"] = 0
    state["requires_human_approval"] = True
    state["goal"] = {
        "raw_request": request,
        "problem": None,
        "desired_outcome": None,
        "non_goals": [],
    }
    state["acceptance_criteria"] = []
    state["phases"]["analysis"]["status"] = "completed"
    state["phases"]["analysis"]["artifact"] = analysis_ref
    state.setdefault("phases", {}).setdefault("analysis_review", {"status": "pending"})
    state["phases"]["analysis_review"]["status"] = "waiting_for_review" if require_analysis_review else "completed"
    state["phases"]["analysis_review"]["artifact"] = analysis_ref
    state["phases"]["alignment"]["status"] = "pending" if require_analysis_review else "waiting_for_approval"
    state["phases"]["alignment"]["artifact"] = acceptance_ref
    state["phases"]["design"]["artifact"] = task_artifact_ref(task_id, "design.md")
    state.setdefault("phases", {}).setdefault("test_authoring", {"status": "pending"})
    state["phases"]["test_authoring"]["artifact"] = task_artifact_ref(task_id, "test-plan.md")
    state["phases"]["testing"]["artifact"] = task_artifact_ref(task_id, "test-plan.md")
    state["analysis_questions"] = draft_analysis_questions(request) if require_analysis_review else []
    state["agents"] = []
    state["updated_at"] = now

    task_artifact_path(root, task_id, "analysis.md").parent.mkdir(parents=True, exist_ok=True)
    prepare_analyst_prompt(root, state)
    manual_criteria = draft_custom_acceptance_items(request, analysis_ref, acceptance_ref)
    if not run_analyst or role_uses_manual(config, "analyst"):
        write_text(task_artifact_path(root, task_id, "analysis.md"), draft_analysis(request))
        write_text(task_artifact_path(root, task_id, "acceptance.json"), json.dumps({"acceptance_criteria": manual_criteria}, indent=2) + "\n")
        write_text(task_artifact_path(root, task_id, "acceptance.md"), draft_acceptance(request, manual_criteria, analysis_ref))
    if run_analyst:
        record_agent_result(
            state,
            run_role(root, config, "analyst", 0, [analysis_ref, acceptance_ref, acceptance_json_ref], task_id=task_id),
        )
    state["acceptance_criteria"] = load_acceptance_criteria(task_artifact_path(root, task_id, "acceptance.json"))
    # Make this task the current one (updates legacy pointer + per-task file).
    set_current_task_id(root, task_id)
    save_state(root, state)
    return state


def approve_task(root: Path, approved_by: str = "requester", task_id: str | None = None) -> dict[str, Any]:
    from .tasks import load_task_state, resolve_task_id, save_task_state

    try:
        tid = resolve_task_id(root, task_id)
    except WorkspaceError:
        legacy = load_state(root)
        status = legacy.get("status")
        if status != "WAITING_FOR_ALIGNMENT":
            raise WorkspaceError(f"Cannot approve while status is {status}.")
        raise
    state = load_task_state(root, tid)
    if state.get("status") != "WAITING_FOR_ALIGNMENT":
        raise WorkspaceError(f"Cannot approve while status is {state.get('status')}.")

    now = utc_now_iso()
    state["status"] = "READY_TO_START"
    state["current_phase"] = "start"
    state["requires_human_approval"] = False
    state["phases"]["alignment"]["status"] = "approved"
    state["phases"]["alignment"]["approved_by"] = approved_by
    state["phases"]["alignment"]["approved_at"] = now
    state["updated_at"] = now
    save_task_state(root, tid, state)
    return state


def cancel_task(root: Path, cancelled_by: str = "requester", task_id: str | None = None) -> dict[str, Any]:
    from .tasks import load_task_state, resolve_task_id, save_task_state

    tid: str
    try:
        tid = resolve_task_id(root, task_id)
    except WorkspaceError:
        # Backwards-compatible behavior: when no task at all, fall through to legacy load.
        legacy = load_state(root)
        status = legacy.get("status")
        if status in {"CREATED", "DONE", "CANCELLED"}:
            raise WorkspaceError(f"Cannot cancel while status is {status}.")
        raise

    state = load_task_state(root, tid)
    status = state.get("status")
    if status in {"CREATED", "DONE", "CANCELLED"}:
        raise WorkspaceError(f"Cannot cancel while status is {status}.")

    now = utc_now_iso()
    state["status"] = "CANCELLED"
    state["current_phase"] = "cancelled"
    state["requires_human_approval"] = False
    state["cancelled_by"] = cancelled_by
    state["cancelled_at"] = now
    state["updated_at"] = now
    save_task_state(root, tid, state)
    return state


def run_one_iteration(root: Path, task_id: str | None = None) -> dict[str, Any]:
    from .tasks import effective_config, load_task_state, resolve_task_id, save_task_state

    tid = resolve_task_id(root, task_id)
    state = load_task_state(root, tid)
    config = effective_config(root, tid)
    status = state.get("status")
    if status not in {"READY_TO_START", "DESIGNING"}:
        raise WorkspaceError(f"Cannot run while status is {status}.")

    iteration = int(state.get("iteration") or 0) + 1
    max_iterations = int(state.get("max_iterations") or config.get("max_iterations") or 7)
    if iteration > max_iterations:
        state["status"] = "BLOCKED"
        state["current_phase"] = "blocked"
        state["updated_at"] = utc_now_iso()
        save_task_state(root, tid, state)
        return state

    state["iteration"] = iteration
    state["status"] = "DESIGNING"
    state["current_phase"] = "design"
    state["phases"]["design"]["status"] = "in_progress"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, tid, state)

    design_ref = artifact_ref(state, "design.md")
    prepare_role_prompt(root, state, "architect", iteration)
    if role_uses_manual(config, "architect"):
        write_text(artifact_file(root, state, "design.md"), draft_design(state, iteration))
    record_agent_result(
        state,
        run_role(root, config, "architect", iteration, [design_ref], task_id=tid),
    )
    state["phases"]["design"]["status"] = "completed"
    state["status"] = "IMPLEMENTING_AND_TESTING"
    state["current_phase"] = "test_authoring"
    state.setdefault("phases", {}).setdefault(
        "test_authoring",
        {"status": "pending", "artifact": artifact_ref(state, "test-plan.md")},
    )
    state["phases"]["test_authoring"]["status"] = "in_progress"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, tid, state)

    test_plan_ref = artifact_ref(state, "test-plan.md")
    prepare_role_prompt(root, state, "tester", iteration, mode="pre_implementation")
    record_agent_result(
        state,
        run_role(root, config, "tester", iteration, [test_plan_ref], task_id=tid),
    )
    state["phases"]["test_authoring"]["status"] = "completed"
    state["current_phase"] = "implementation"
    state["phases"]["implementation"]["status"] = "in_progress"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, tid, state)

    prepare_role_prompt(root, state, "implementer", iteration)
    record_agent_result(state, run_role(root, config, "implementer", iteration, [], task_id=tid))
    state["phases"]["implementation"]["status"] = "completed"
    state["current_phase"] = "testing"
    state["phases"]["testing"]["status"] = "in_progress"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, tid, state)

    test_results = run_test_commands(root, list(config.get("test_commands") or []), iteration, task_id=tid)
    prepare_role_prompt(root, state, "tester", iteration, mode="post_implementation")
    if role_uses_manual(config, "tester"):
        write_text(artifact_file(root, state, "test-plan.md"), draft_test_plan(state, test_results))
    record_agent_result(
        state,
        run_role(root, config, "tester", iteration, [test_plan_ref], task_id=tid),
    )
    state["phases"]["testing"]["status"] = "completed"
    state["status"] = "REVIEWING"
    state["current_phase"] = "review"
    state["phases"]["review"]["status"] = "in_progress"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, tid, state)

    review_name = f"review-{iteration:03d}.json"
    review_ref = artifact_ref(state, review_name)
    review_path = artifact_file(root, state, review_name)
    prepare_role_prompt(root, state, "reviewer", iteration, review_name=review_name)
    if role_uses_manual(config, "reviewer"):
        review_data = manual_review(state, test_results)
        write_text(review_path, json.dumps(review_data, indent=2) + "\n")
    record_agent_result(
        state,
        run_role(root, config, "reviewer", iteration, [review_ref], task_id=tid),
    )
    review = load_review(review_path)
    gate = evaluate_gate(state, review)

    state["phases"]["review"]["last_review"] = review_ref
    state["phases"]["review"]["status"] = gate.lower()
    for result in review.get("acceptance_results", []):
        for criterion in state.get("acceptance_criteria", []):
            if criterion.get("id") == result.get("criteria_id"):
                criterion["status"] = result.get("status", criterion.get("status"))
                criterion["evidence"] = result.get("evidence", criterion.get("evidence"))

    if gate == "APPROVED":
        state["status"] = "DONE"
        state["current_phase"] = "done"
        final_ref = artifact_ref(state, "final-report.md")
        prepare_role_prompt(root, state, "integrator", iteration)
        if role_uses_manual(config, "integrator"):
            write_text(artifact_file(root, state, "final-report.md"), draft_final_report(state, review))
        record_agent_result(
            state,
            run_role(root, config, "integrator", iteration, [final_ref], task_id=tid),
        )
    elif gate == "BLOCKED":
        state["status"] = "WAITING_FOR_HUMAN"
        state["current_phase"] = "human_review"
        state["requires_human_approval"] = True
    else:
        if iteration >= max_iterations:
            state["status"] = "BLOCKED"
            state["current_phase"] = "blocked"
        else:
            state["status"] = "DESIGNING"
            state["current_phase"] = "design"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, tid, state)
    return state


def run_task(root: Path, task_id: str | None = None) -> dict[str, Any]:
    from .tasks import load_task_state, resolve_task_id

    tid = resolve_task_id(root, task_id)
    state = load_task_state(root, tid)
    if state.get("status") not in {"READY_TO_START", "DESIGNING"}:
        raise WorkspaceError(f"Cannot run while status is {state.get('status')}.")

    while state.get("status") in {"READY_TO_START", "DESIGNING"}:
        previous_iteration = int(state.get("iteration") or 0)
        state = run_one_iteration(root, tid)
        if state.get("status") != "DESIGNING":
            break
        if int(state.get("iteration") or 0) <= previous_iteration:
            raise WorkspaceError("Iteration did not advance; refusing to continue automatic loop.")
    return state
