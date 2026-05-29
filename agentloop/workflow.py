"""Workflow operations for AgentLoop phases."""

from __future__ import annotations

import json
import re
import threading
import traceback
from pathlib import Path
from typing import Any

from .adapters import run_role, runtime_for_role
from .handoff import (
    append_context_log,
    collect_upstream_handoffs,
    handoff_output_contract,
    handoff_output_contract_brief,
    handoff_path,
    handoff_ref,
    next_turn_for_role,
    render_upstream_handoff_block,
    write_handoff_stub,
)
from .models import default_state, utc_now_iso
from .quality import evaluate_gate, load_review
from .runner import run_test_commands
from .sessions import generate_session_id, get_role_session, runtime_supports_resume, update_role_session
from .transcripts import write_transcript
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


_CJK_RANGES = (
    (0x3040, 0x30FF),   # Japanese kana
    (0x3400, 0x4DBF),   # CJK Extension A
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs (covers Chinese + most Kanji)
    (0xAC00, 0xD7AF),   # Hangul
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
)


def detect_language(text: str) -> str:
    if not text:
        return "en"
    for ch in text:
        code = ord(ch)
        for lo, hi in _CJK_RANGES:
            if lo <= code <= hi:
                if 0xAC00 <= code <= 0xD7AF:
                    return "ko"
                if 0x3040 <= code <= 0x30FF:
                    return "ja"
                return "zh"
    return "en"


_LANGUAGE_DISPLAY_NAMES = {
    "zh": "Chinese (中文)",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
    "en": "English",
}


def language_directive(state: dict[str, Any]) -> str:
    lang = (state.get("goal", {}) or {}).get("language") or "en"
    if lang == "en":
        return ""
    display = _LANGUAGE_DISPLAY_NAMES.get(lang, lang)
    return (
        f"User's working language: **{display}**. "
        "Write all human-facing prose (analysis, design rationale, question text, summaries, "
        "acceptance criterion descriptions, review comments) in that language. "
        "Keep code, file paths, identifiers, JSON keys, structured field names, status enums, "
        "and shell commands in English.\n\n"
    )


def _normalize_code_path(raw: str) -> tuple[Path, str]:
    candidate = Path(str(raw).strip().strip('"').strip("'")).expanduser()
    if not candidate.is_absolute():
        candidate = candidate.resolve()
    else:
        candidate = candidate.resolve()
    if not candidate.exists():
        raise WorkspaceError(f"Code path does not exist: {candidate}")
    display = str(candidate).replace("\\", "/")
    return candidate, display


def code_path_directive(state: dict[str, Any]) -> str:
    goal = state.get("goal", {}) or {}
    raw = (goal.get("code_path") or "").strip()
    if not raw:
        return ""
    kind = (goal.get("code_path_kind") or "").strip() or "path"
    if kind == "file":
        path_obj = Path(raw)
        parent = str(path_obj.parent).replace("\\", "/") or "/"
        return (
            f"Task code path: `{raw}` (single file). "
            f"Treat its parent directory `{parent}` as the working directory. "
            "Focus analysis on this file and its immediate neighbors; expand scope only when the task requires it.\n\n"
        )
    return (
        f"Task code path: `{raw}` (directory). "
        "Treat it as the working directory and limit analysis to files under it unless the task explicitly requires looking elsewhere. "
        "All file paths cited in your output must be relative to this directory.\n\n"
    )


def effective_cwd_for_task(root: Path, state: dict[str, Any]) -> Path:
    goal = state.get("goal", {}) or {}
    raw = (goal.get("code_path") or "").strip()
    if not raw:
        return root
    path_obj = Path(raw)
    if not path_obj.exists():
        return root
    if path_obj.is_file():
        return path_obj.parent
    return path_obj


def create_task_id(raw_request: str) -> str:
    compact_time = utc_now_iso().replace("-", "").replace(":", "").split("+")[0].replace("T", "-")
    return f"{compact_time}-{slugify(raw_request)}"


def requirement_fragments(raw_request: str) -> list[str]:
    normalized = re.sub(r"[\r\n]+", " ", raw_request.strip())
    parts = re.split(r"[;；。.!?？]+|要求[:：]", normalized)
    fragments: list[str] = []
    for part in parts:
        fragment = part.strip(" ，,、")
        if len(fragment) >= 4 and fragment not in fragments:
            fragments.append(fragment)
    return fragments or [raw_request.strip()]


# ---------------------------------------------------------------------------
# Framing helpers
# ---------------------------------------------------------------------------


def _initial_open_questions(raw_request: str, prior: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if prior:
        # Carry forward unanswered + blocking questions; reuse answers.
        return prior
    lower = raw_request.lower()
    questions: list[dict[str, Any]] = []
    if any(token in lower for token in ["performance", "slow", "too slow", "性能", "太慢", "latency", "timeout"]):
        questions.append(
            {
                "id": "Q-1",
                "question": "Is there a specific performance target (latency, throughput, percentile), or should AgentLoop define a conservative baseline?",
                "blocking": True,
                "reason": "A measurable target is needed before research can pick a baseline to beat.",
                "answer": "",
            }
        )
    if not re.search(r"[\w./\\-]+\.(py|js|ts|tsx|jsx|json|md|html|css)\b", raw_request):
        questions.append(
            {
                "id": "Q-FILES",
                "question": "Which files, modules, or subsystem should AgentLoop investigate first?",
                "blocking": True,
                "reason": "Investigation scope is ambiguous without a concrete starting point.",
                "answer": "",
            }
        )
    questions.append(
        {
            "id": "Q-OUTCOME",
            "question": "What does success look like from the requester's perspective? Any non-goals to keep out of scope?",
            "blocking": False,
            "reason": "Clarifies acceptance signals and prevents scope creep.",
            "answer": "",
        }
    )
    return questions


_PLACEHOLDER_ANSWERS = {"", "unanswered", "n/a", "na", "tbd", "none"}


def _ready_for_research(questions: list[dict[str, Any]]) -> bool:
    for item in questions:
        if not isinstance(item, dict):
            continue
        answer = str(item.get("answer") or "").strip().lower()
        if item.get("blocking") and answer in _PLACEHOLDER_ANSWERS:
            return False
    return True


def draft_framing_json(raw_request: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
    fragments = requirement_fragments(raw_request)
    assumptions = ["Implementation stays inside the current workspace."]
    if not _ready_for_research(questions):
        assumptions.append("Blocking questions remain; do not begin research until they are answered.")
    return {
        "problem_statement": fragments[0] if fragments else raw_request.strip(),
        "non_goals": [],
        "assumptions": assumptions,
        "open_questions": questions,
        "ready_for_research": _ready_for_research(questions),
    }


def draft_framing(raw_request: str, framing_json: dict[str, Any]) -> str:
    fragments = requirement_fragments(raw_request)
    bullets = "\n".join(f"- {fragment}" for fragment in fragments)
    open_lines = []
    for item in framing_json.get("open_questions", []):
        if not isinstance(item, dict):
            continue
        marker = "blocking" if item.get("blocking") else "optional"
        answer = str(item.get("answer") or "").strip()
        answer_line = f"\n  Answer: {answer}" if answer else ""
        open_lines.append(
            f"- {item.get('id')} ({marker}): {item.get('question')}\n  Reason: {item.get('reason', '')}" + answer_line
        )
    open_block = "\n".join(open_lines) or "- None."
    assumption_block = "\n".join(f"- {a}" for a in framing_json.get("assumptions", [])) or "- None."
    non_goal_block = "\n".join(f"- {a}" for a in framing_json.get("non_goals", [])) or "- None recorded."
    ready_line = "Ready for research." if framing_json.get("ready_for_research") else "Blocking questions remain. Answer them to unlock research."
    return f"""# Problem Framing

## Raw Request

{raw_request}

## Problem Statement

{framing_json.get("problem_statement", "")}

## What the requester is asking for

{bullets}

## Non-Goals

{non_goal_block}

## Assumptions

{assumption_block}

## Open Questions

{open_block}

## Status

{ready_line}
"""


# ---------------------------------------------------------------------------
# Investigator + Architect helpers
# ---------------------------------------------------------------------------


def draft_research(state: dict[str, Any]) -> str:
    request = state.get("goal", {}).get("raw_request") or state.get("title") or "Untitled task"
    framing = state.get("framing") or {}
    statement = framing.get("problem_statement") or request
    return f"""# Research

## Problem

{statement}

## Current-state archive

- Investigator should list the relevant files (file:line) and summarize today's behavior.
- For performance work, record baseline measurements, repro commands, and contributing call sites.

## Affected modules

- To be filled in by the investigator with concrete file references.

## Open risks discovered during investigation

- None recorded yet.
"""


def draft_proposal(state: dict[str, Any]) -> str:
    request = state.get("goal", {}).get("raw_request") or state.get("title") or "Untitled task"
    framing = state.get("framing") or {}
    statement = framing.get("problem_statement") or request
    return f"""# Solution Proposal

## Problem

{statement}

## Recommended Approach

- Architect should describe the chosen approach and why it satisfies the framing.

## Alternatives Considered

- Architect should list the alternatives evaluated and the reason each was rejected.

## Risks & Open Trade-offs

- To be filled in by the architect.
"""


def draft_test_plan_from_proposal(state: dict[str, Any]) -> str:
    request = state.get("goal", {}).get("raw_request") or state.get("title") or "Untitled task"
    criteria = state.get("acceptance_criteria") or []
    automated = [item for item in criteria if str(item.get("verification") or "").lower() in {"automated_test", "unit_test", "test"}]
    automated_lines = "\n".join(f"- {item.get('id')}: {item.get('evidence') or item.get('description')}" for item in automated)
    if not automated_lines:
        automated_lines = "- No automated acceptance criterion was inferred; reviewer should require manual evidence or request a focused test if code behavior changes."
    return f"""# Test Plan

## Task

{request}

## Pre-Implementation Test Authoring

- Tester creates or updates focused regression tests for the approved task before implementation.
- For bug, regression, performance, slow, or timeout tasks, the plan must include a regression or performance signal before reviewer approval.

## Required Evidence

{automated_lines}

## Reviewer Gate

- Approval is blocked unless required automated criteria have passing command evidence.
- If a test cannot run, reviewer must report `CHANGES_REQUIRED` or `BLOCKED` with the reason.
"""


def draft_acceptance_items(raw_request: str, acceptance_ref: str) -> list[dict[str, Any]]:
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
            "latency",
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
    return items


def draft_acceptance(raw_request: str, criteria: list[dict[str, Any]], framing_ref: str) -> str:
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

Review this file together with `{framing_ref}`, the research, and the proposal. If the scope is correct, run:

```powershell
python -m agentloop approve
```
"""


# ---------------------------------------------------------------------------
# Prompt preparation
# ---------------------------------------------------------------------------


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


def _load_pre_scan_text(root: Path, state: dict[str, Any]) -> str:
    task_id = task_id_or_error(state)
    path = task_artifact_path(root, task_id, "pre-scan.md")
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def prepare_scanner_prompt(root: Path, state: dict[str, Any]) -> None:
    request = state.get("goal", {}).get("raw_request") or state.get("title") or "Untitled task"
    pre_scan_ref = artifact_ref(state, "pre-scan.md")
    task_id = task_id_or_error(state)
    turn = next_turn_for_role(state, "scanner")
    kind = (state.get("goal", {}) or {}).get("code_path_kind") or "directory"
    scope_hint = (
        "The code path is a single file. Read that file plus its closest neighbors "
        "(same directory, files it imports, files that import it). Do not wander further unless clearly needed."
        if kind == "file"
        else "The code path is a directory. Start with the file tree (top 2-3 levels), then read the most relevant files."
    )
    body = (
        "# Scanner Prompt\n\n"
        f"{language_directive(state)}"
        f"{code_path_directive(state)}"
        f"Task request:\n{request}\n\n"
        "You are a pre-framing scanner. Your job is to ground the framer in the actual codebase "
        "so it can ask sharp, file-specific clarifying questions instead of generic ones. "
        "Do NOT propose a solution, do NOT frame the problem, do NOT write framing questions.\n\n"
        f"{scope_hint}\n\n"
        "Budget: read at most ~15 files, keep your output under ~30k characters total. "
        "Prefer README, package manifests (package.json / pyproject.toml / Cargo.toml / etc.), "
        "obvious entry points, files named or implied in the task request, and recently-modified files.\n\n"
        "Required output:\n"
        f"- Write `{pre_scan_ref}` with the following markdown sections (in this order):\n"
        "  1. `## Project overview` — what this project is, language/stack, one paragraph.\n"
        "  2. `## Key files & purpose` — bullet list of the files you read and one line on each.\n"
        "  3. `## Patterns & conventions observed` — naming, structure, testing style, anything a contributor needs to respect.\n"
        "  4. `## Files most relevant to this task` — the subset the framer/investigator should focus on, with one line of justification each.\n"
        "  5. `## Open uncertainties for the framer` — concrete unknowns the framer should ask the requester about (do NOT answer them yourself).\n\n"
        "Keep it dense and specific. Quote file paths verbatim. No filler sentences.\n\n"
        f"{handoff_output_contract(task_id, 'scanner', turn)}"
    )
    write_role_prompt(root, "scanner", body)


def prepare_framer_prompt(root: Path, state: dict[str, Any], mode: str = "initial") -> None:
    request = state.get("goal", {}).get("raw_request") or state.get("title") or "Untitled task"
    framing_ref = artifact_ref(state, "framing.md")
    framing_json_ref = artifact_ref(state, "framing.json")
    task_id = task_id_or_error(state)
    turn = next_turn_for_role(state, "framer")
    upstream_block = render_upstream_handoff_block(collect_upstream_handoffs(root, state, "framer"))
    prior_qa = state.get("framing_questions") or []
    prior_block = "\n".join(
        f"- {item.get('id')}: {item.get('question')} (answer: {str(item.get('answer') or '').strip() or 'unanswered'})"
        for item in prior_qa
        if isinstance(item, dict)
    ) or "- (none yet)"

    if mode == "resume_incremental":
        answered = [
            item for item in prior_qa
            if isinstance(item, dict) and str(item.get("answer") or "").strip()
        ]
        answer_lines = "\n".join(
            f"- {item.get('id')}: {item.get('question')}\n  Answer: {str(item.get('answer') or '').strip()}"
            for item in answered
        ) or "- (no new answers)"
        body = (
            f"# Framer Prompt (resume turn {turn})\n\n"
            "The requester answered your open questions. Prior context is in this session — do NOT restate it.\n\n"
            "## New answers\n"
            f"{answer_lines}\n\n"
            "## What to do\n"
            f"- Patch `{framing_ref}` in place (only the assumptions/open questions affected).\n"
            f"- Update `{framing_json_ref}`: fill `answer` for each answered question; set `ready_for_research` based on remaining blockers.\n\n"
            f"{handoff_output_contract_brief(task_id, 'framer', turn)}"
        )
    else:
        pre_scan_text = _load_pre_scan_text(root, state)
        pre_scan_block = (
            "Codebase context (auto-generated pre-scan — treat as ground truth about what's in the code):\n"
            f"{pre_scan_text}\n\n"
            if pre_scan_text
            else ""
        )
        body = (
            "# Framer Prompt\n\n"
            f"{language_directive(state)}"
            f"{code_path_directive(state)}"
            f"{pre_scan_block}"
            f"{upstream_block}"
            f"Task request:\n{request}\n\n"
            "Frame the problem so research and implementation can later proceed without ambiguity. Do NOT propose a solution yet.\n\n"
            f"Prior Q&A:\n{prior_block}\n\n"
            "Required outputs:\n"
            f"- Write a human-readable framing to `{framing_ref}` (problem statement, non-goals, assumptions, open questions).\n"
            f"- Write structured framing JSON to `{framing_json_ref}` with the schema "
            "{problem_statement, non_goals[], assumptions[], open_questions[{id,question,blocking,reason,answer}], ready_for_research}.\n"
            "- Leave `answer` as an empty string (\"\") when the requester has not answered. Do NOT write placeholder text like \"unanswered\", \"n/a\", or \"tbd\".\n"
            "- Set `ready_for_research` to true only when no blocking question is unanswered.\n"
            "- Stop after producing these two files; research starts only after the requester clicks \"Start research\".\n\n"
            f"{handoff_output_contract(task_id, 'framer', turn)}"
        )
    write_role_prompt(root, "framer", body)


def prepare_investigator_prompt(root: Path, state: dict[str, Any], mode: str = "initial") -> None:
    request = state.get("goal", {}).get("raw_request") or state.get("title") or "Untitled task"
    framing_ref = artifact_ref(state, "framing.md")
    research_ref = artifact_ref(state, "research.md")
    task_id = task_id_or_error(state)
    turn = next_turn_for_role(state, "investigator")
    upstream_block = render_upstream_handoff_block(collect_upstream_handoffs(root, state, "investigator"))
    if mode == "resume_incremental":
        body = (
            f"# Investigator Prompt (resume turn {turn})\n\n"
            "Your prior research context is in this session — do NOT restate it.\n\n"
            "## What changed\n"
            f"{upstream_block}"
            "## What to do\n"
            f"- Re-check whether `{research_ref}` still reflects current code state and the latest framing.\n"
            "- Patch only the sections affected by upstream changes; leave the rest as-is.\n\n"
            f"{handoff_output_contract_brief(task_id, 'investigator', turn)}"
        )
    else:
        body = (
            "# Investigator Prompt\n\n"
            f"{language_directive(state)}"
            f"{code_path_directive(state)}"
            f"{upstream_block}"
            f"Task request:\n{request}\n\n"
            f"Framing input: `{framing_ref}` (treat as approved by the requester).\n\n"
            "Investigate the current state of the relevant code, configuration, and behavior. Do NOT propose changes yet.\n\n"
            "Required outputs:\n"
            f"- Write the research to `{research_ref}` with: (1) current-state archive (file:line citations), "
            "(2) baseline data or reproduction, (3) affected modules, (4) any open risks you discovered.\n"
            "- Only describe what exists today; leave the recommendation to the architect.\n\n"
            f"{handoff_output_contract(task_id, 'investigator', turn)}"
        )
    write_role_prompt(root, "investigator", body)


def prepare_architect_design_prompt(root: Path, state: dict[str, Any], mode: str = "initial") -> None:
    request = state.get("goal", {}).get("raw_request") or state.get("title") or "Untitled task"
    framing_ref = artifact_ref(state, "framing.md")
    research_ref = artifact_ref(state, "research.md")
    proposal_ref = artifact_ref(state, "proposal.md")
    acceptance_ref = artifact_ref(state, "acceptance.md")
    acceptance_json_ref = artifact_ref(state, "acceptance.json")
    test_plan_ref = artifact_ref(state, "test-plan.md")
    task_id = task_id_or_error(state)
    turn = next_turn_for_role(state, "architect")
    upstream_block = render_upstream_handoff_block(collect_upstream_handoffs(root, state, "architect"))
    if mode == "resume_incremental":
        body = (
            f"# Architect Prompt (resume turn {turn})\n\n"
            "Your prior design context is in this session — do NOT restate it.\n\n"
            "## What changed\n"
            f"{upstream_block}"
            "## What to do\n"
            f"- Patch `{proposal_ref}`, `{acceptance_ref}`, `{acceptance_json_ref}`, `{test_plan_ref}` "
            "to reflect the upstream delta. Edit in place; do not re-emit unchanged sections.\n\n"
            f"{handoff_output_contract_brief(task_id, 'architect', turn)}"
        )
    else:
        body = (
            "# Architect Prompt (pre-approval)\n\n"
            f"{language_directive(state)}"
            f"{code_path_directive(state)}"
            f"{upstream_block}"
            f"Task request:\n{request}\n\n"
            f"Inputs: `{framing_ref}`, `{research_ref}`.\n\n"
            "Required outputs:\n"
            f"- `{proposal_ref}` — recommended approach, alternatives considered, risks.\n"
            f"- `{acceptance_ref}` — human-readable acceptance criteria.\n"
            f"- `{acceptance_json_ref}` — structured `{{acceptance_criteria: [{{id, description, verification, required, status, evidence}}]}}`.\n"
            f"- `{test_plan_ref}` — pre-implementation test plan with required evidence and reviewer gate.\n\n"
            "For bug, regression, performance, slow, timeout, or code-change tasks, include at least one required criterion with verification `automated_test`.\n"
            "Stop after producing these files; execution starts only after the requester approves.\n\n"
            f"{handoff_output_contract(task_id, 'architect', turn)}"
        )
    write_role_prompt(root, "architect", body)


def prepare_role_prompt(
    root: Path,
    state: dict[str, Any],
    role: str,
    iteration: int,
    review_name: str | None = None,
    mode: str | None = None,
    session_mode: str = "initial",
) -> None:
    request = state.get("goal", {}).get("raw_request") or state.get("title") or "Untitled task"
    has_snapshot = bool((state.get("runtime_input") or {}).get("files"))
    proposal_name = "proposal.approved.md" if has_snapshot else "proposal.md"
    test_plan_name = "test-plan.approved.md" if has_snapshot else "test-plan.md"
    proposal_ref = artifact_ref(state, proposal_name)
    test_plan_ref = artifact_ref(state, test_plan_name)
    final_ref = artifact_ref(state, "final-report.md")
    review_ref = artifact_ref(state, review_name or f"review-{iteration:03d}.json")
    artifact_dir_ref = task_artifact_ref(task_id_or_error(state), "")
    task_id = task_id_or_error(state)
    turn = next_turn_for_role(state, role)
    upstream_block = render_upstream_handoff_block(collect_upstream_handoffs(root, state, role))

    if session_mode == "resume_incremental":
        delta_intro = (
            f"# {role.title()} Prompt (resume turn {turn}, iteration {iteration})\n\n"
            "Your prior context is in this session — do NOT restate it.\n\n"
            "## What changed since your last turn\n"
            f"{upstream_block}"
            f"Task artifact directory: `{artifact_dir_ref}`\n"
        )
        role_delta = {
            "implementer": (
                f"{delta_intro}\n"
                "## What to do\n"
                "- Apply only the additional changes implied by the upstream delta above.\n"
                "- Preserve work from prior turns; do not re-implement what is already in place.\n\n"
                f"{handoff_output_contract_brief(task_id, 'implementer', turn)}"
            ),
            "tester": (
                f"{delta_intro}\n"
                "## What to do\n"
                f"- Update `{test_plan_ref}` to reflect new evidence or new tests required by the upstream delta.\n"
                "- Re-run only the tests whose inputs changed; record updated commands, exit codes, and timing.\n\n"
                f"{handoff_output_contract_brief(task_id, 'tester', turn)}"
            ),
            "reviewer": (
                f"{delta_intro}\n"
                "## What to do\n"
                f"- Re-review against acceptance criteria and write strict JSON to `{review_ref}` (same schema as turn 1).\n"
                "- Focus on the delta: which previously-open comments are now resolved, what new issues appear.\n\n"
                f"{handoff_output_contract_brief(task_id, 'reviewer', turn)}"
            ),
            "integrator": (
                f"{delta_intro}\n"
                "## What to do\n"
                f"- Update `{final_ref}` if the upstream delta changed outcomes; otherwise confirm prior report still holds.\n\n"
                f"{handoff_output_contract_brief(task_id, 'integrator', turn)}"
            ),
        }
        if role in role_delta:
            write_role_prompt(root, role, role_delta[role])
            return

    common = (
        f"{language_directive(state)}"
        f"{code_path_directive(state)}"
        f"{upstream_block}"
        f"Task: {request}\n"
        f"Iteration: {iteration}\n"
        f"Task artifact directory: `{artifact_dir_ref}`\n"
        f"Approved proposal: `{proposal_ref}`\n"
        "Use paths exactly as written. Do not write task artifacts to `.agentloop/artifacts/`.\n"
    )
    tester_instruction = (
        f"Produce the test plan and evidence at `{test_plan_ref}`. Add or update tests as needed.\n"
    )
    if mode == "pre_implementation":
        tester_instruction = (
            f"Before implementation, create or update focused regression tests for the approved task and update the plan at `{test_plan_ref}`.\n"
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
        "implementer": (
            "# Implementer Prompt\n\n"
            f"{common}\n"
            "Implement the approved task in the workspace. Keep changes scoped to the proposal.\n\n"
            f"{handoff_output_contract(task_id, 'implementer', turn)}"
        ),
        "tester": (
            "# Tester Prompt\n\n"
            f"{common}\n"
            f"{tester_instruction}\n"
            f"{handoff_output_contract(task_id, 'tester', turn)}"
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
            "or updated a focused regression/performance test and the review records passing evidence for it.\n\n"
            f"{handoff_output_contract(task_id, 'reviewer', turn)}"
        ),
        "integrator": (
            "# Integrator Prompt\n\n"
            f"{common}\n"
            f"Produce the final report at `{final_ref}` after the task is approved.\n\n"
            f"{handoff_output_contract(task_id, 'integrator', turn)}"
        ),
    }
    if role in prompts:
        write_role_prompt(root, role, prompts[role])


# ---------------------------------------------------------------------------
# Manual fallbacks
# ---------------------------------------------------------------------------


def manual_review(state: dict[str, Any], test_results: list[dict[str, Any]]) -> dict[str, Any]:
    test_failure = any(item.get("exit_code") not in {0, None} for item in test_results)
    acceptance_results = []
    for criterion in state.get("acceptance_criteria", []):
        status = criterion.get("status")
        if not test_failure and status == "pending":
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
        "summary": "Manual runtime generated required artifacts and no configured tests failed.",
        "open_medium_high_count": 0,
        "comments": [],
        "acceptance_results": acceptance_results,
        "test_results": test_results,
    }


def draft_test_plan_with_results(state: dict[str, Any], test_results: list[dict[str, Any]]) -> str:
    commands = test_results or []
    command_lines = "\n".join(
        f"- `{item['command']}` -> exit {item['exit_code']} ({item['log']})" for item in commands
    ) or "- No test commands configured."
    return f"""# Test Plan

## Scope

Validate the approved proposal through configured commands and focused regression tests.

## Test Command Results

{command_lines}
"""


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

- `{artifact_ref(state, "framing.md")}`
- `{artifact_ref(state, "research.md")}`
- `{artifact_ref(state, "proposal.md")}`
- `{artifact_ref(state, "acceptance.md")}`
- `{artifact_ref(state, "test-plan.md")}`
- `{review_artifact}`
"""


def role_uses_manual(config: dict[str, Any], role: str) -> bool:
    _, runtime = runtime_for_role(config, role)
    return runtime.get("adapter", "command") == "manual"


def record_agent_result(state: dict[str, Any], result: dict[str, Any]) -> None:
    state.setdefault("agents", []).append(result)


def prompt_mode_for_role(state: dict[str, Any], config: dict[str, Any], role: str) -> str:
    """Return 'initial' or 'resume_incremental' depending on prior session state.

    Falls back to 'initial' when:
    - no prior session for this role
    - runtime doesn't support resume
    - the runtime has changed since the last turn (invalidates the session)
    """
    try:
        runtime_name, runtime = runtime_for_role(config, role)
    except WorkspaceError:
        return "initial"
    if not runtime.get("supports_resume"):
        return "initial"
    sess = get_role_session(state, role, runtime_name)
    if not sess:
        return "initial"
    return "resume_incremental"


def _run_role_with_session(
    root: Path,
    state: dict[str, Any],
    config: dict[str, Any],
    role: str,
    iteration: int,
    required_artifacts: list[str],
    *,
    task_id: str | None = None,
) -> dict[str, Any]:
    runtime_name, runtime_cfg = runtime_for_role(config, role)
    sess = get_role_session(state, role, runtime_name)
    supports_resume = runtime_supports_resume(runtime_cfg)
    if sess and sess.get("session_id"):
        session_id = sess["session_id"]
        resume = True
    elif supports_resume and not runtime_cfg.get("session_id_regex"):
        # Runtime accepts a caller-supplied session id (e.g. Claude Code's
        # `--session-id <uuid>`). Pre-generate one so the very first turn already
        # owns a stable id we can resume against — no need to scrape stdout.
        session_id = generate_session_id()
        resume = False
        update_role_session(state, role, session_id=session_id, runtime_name=runtime_name)
    else:
        # Runtime mints its own session id (e.g. Codex). Run cold, then extract
        # the id from stdout via `session_id_regex` and persist it.
        session_id = None
        resume = False
    result = run_role(
        root,
        config,
        role,
        iteration,
        required_artifacts,
        task_id=task_id,
        session_id=session_id,
        resume=resume,
    )
    new_sid = result.get("session_id")
    if new_sid:
        update_role_session(state, role, session_id=new_sid, runtime_name=runtime_name)
    if task_id:
        turn = next_turn_for_role(state, role)
        prompt_rel = f".agentloop/prompts/{role}.md"
        try:
            tref = write_transcript(
                root,
                task_id,
                role,
                turn,
                runtime=runtime_name,
                adapter_result=result,
                prompt_ref=prompt_rel,
            )
            result["transcript_ref"] = tref
        except OSError:
            result["transcript_ref"] = None
    return result


def _post_role_handoff(
    root: Path,
    state: dict[str, Any],
    config: dict[str, Any],
    role: str,
    *,
    fallback_summary: str | None = None,
) -> None:
    """After a role runs, ensure a handoff file exists and append context_log.

    For manual runtimes, write a stub if the role didn't produce one. For other
    runtimes, mark `handoff_present=False` when the file is missing so the next
    role can still find the most recent real handoff.
    """
    task_id = task_id_or_error(state)
    turn = next_turn_for_role(state, role)
    runtime_name, _ = runtime_for_role(config, role)
    path = handoff_path(root, task_id, role, turn)
    if not path.exists() and role_uses_manual(config, role):
        write_handoff_stub(
            root,
            task_id,
            role,
            turn,
            fallback_summary or f"{role} completed via manual runtime (auto-generated stub).",
        )
    present = path.exists()
    transcript_ref_value: str | None = None
    agents = state.get("agents") or []
    for entry in reversed(agents):
        if isinstance(entry, dict) and entry.get("role") == role:
            tref = entry.get("transcript_ref")
            if isinstance(tref, str) and tref:
                transcript_ref_value = tref
            break
    append_context_log(
        state,
        role=role,
        turn=turn,
        runtime=runtime_name,
        handoff_ref_value=handoff_ref(task_id, role, turn) if present else None,
        transcript_ref=transcript_ref_value,
        handoff_present=present,
    )


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


# ---------------------------------------------------------------------------
# Public workflow entry points
# ---------------------------------------------------------------------------


def _run_scanner(root: Path, state: dict[str, Any], config: dict[str, Any], task_id: str) -> None:
    """Run the codebase pre-scanner before framing. Non-fatal: errors are recorded but do not abort framing."""
    code_path = (state.get("goal", {}) or {}).get("code_path") or ""
    if not str(code_path).strip():
        return
    if task_artifact_path(root, task_id, "pre-scan.md").exists():
        return
    if role_uses_manual(config, "scanner"):
        return
    pre_scan_ref = task_artifact_ref(task_id, "pre-scan.md")
    try:
        prepare_scanner_prompt(root, state)
        record_agent_result(
            state,
            _run_role_with_session(root, state, config, "scanner", 0, [pre_scan_ref], task_id=task_id),
        )
    except Exception as exc:  # pragma: no cover - non-fatal pre-step
        record_agent_result(
            state,
            {"role": "scanner", "error": f"{exc.__class__.__name__}: {exc}"},
        )


def _run_framer(root: Path, state: dict[str, Any], config: dict[str, Any], task_id: str) -> None:
    framer_mode = prompt_mode_for_role(state, config, "framer")
    if framer_mode == "initial":
        _run_scanner(root, state, config, task_id)
    framing_ref = task_artifact_ref(task_id, "framing.md")
    framing_json_ref = task_artifact_ref(task_id, "framing.json")
    prepare_framer_prompt(root, state, mode=framer_mode)
    if role_uses_manual(config, "framer"):
        framing_path = task_artifact_path(root, task_id, "framing.md")
        framing_json_path = task_artifact_path(root, task_id, "framing.json")
        framing_path.parent.mkdir(parents=True, exist_ok=True)
        framing_json = draft_framing_json(
            state.get("goal", {}).get("raw_request") or "",
            state.get("framing_questions") or [],
        )
        framing_path.write_text(
            draft_framing(state.get("goal", {}).get("raw_request") or "", framing_json),
            encoding="utf-8",
        )
        framing_json_path.write_text(json.dumps(framing_json, indent=2) + "\n", encoding="utf-8")
    record_agent_result(
        state,
        _run_role_with_session(root, state, config, "framer", 0, [framing_ref, framing_json_ref], task_id=task_id),
    )
    _post_role_handoff(root, state, config, "framer", fallback_summary="Framer drafted framing.md and framing.json.")


def _finalize_framing_state(root: Path, state: dict[str, Any], task_id: str) -> None:
    framing_json = _load_framing_json(root, task_id)
    if framing_json.get("open_questions"):
        state["framing_questions"] = framing_json["open_questions"]
    state["framing"] = framing_json
    state["status"] = "FRAMING_REVIEW"
    state["current_phase"] = "framing_review"
    state["framing_running"] = False
    state["framing_error"] = None
    state["updated_at"] = utc_now_iso()


def _read_role_stderr_tail(root: Path, state: dict[str, Any], role: str,
                            max_lines: int = 40) -> str:
    for entry in reversed(state.get("agents") or []):
        if not isinstance(entry, dict) or entry.get("role") != role:
            continue
        log_rel = entry.get("stderr_log")
        if not log_rel:
            return ""
        path = root / log_rel
        if not path.exists():
            return ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines[-max_lines:])
    return ""


def _run_framer_in_background(root: Path, task_id: str) -> None:
    from .tasks import effective_config, load_task_state, save_task_state

    try:
        state = load_task_state(root, task_id)
        config = effective_config(root, task_id)
        _run_framer(root, state, config, task_id)
        # Detect silent runtime failure: framer process exited cleanly but
        # produced no handoff JSON for this turn. Without this check the task
        # would loop forever — _finalize_framing_state would reread the stale
        # framing.json, push the same questions, and bounce back to FRAMING_REVIEW.
        last_log = next(
            (e for e in reversed(state.get("context_log") or [])
             if isinstance(e, dict) and e.get("role") == "framer"),
            None,
        )
        if last_log and not last_log.get("handoff_present"):
            stderr_tail = _read_role_stderr_tail(root, state, "framer")
            state["framing_running"] = False
            state["status"] = "FRAMING_REVIEW"
            state["current_phase"] = "framing_review"
            state["framing_error"] = (
                "Framer runtime exited without writing a handoff JSON "
                "(likely a silent runtime failure). Check the runtime config "
                "or switch the framer role to a different runtime, then resubmit."
                + (f"\n\nstderr tail:\n{stderr_tail}" if stderr_tail else "")
            )
            state["updated_at"] = utc_now_iso()
            save_task_state(root, task_id, state)
            return
        _finalize_framing_state(root, state, task_id)
        save_task_state(root, task_id, state)
    except Exception as exc:  # pragma: no cover - reported through state
        try:
            state = load_task_state(root, task_id)
            state["framing_running"] = False
            state["framing_error"] = f"{exc.__class__.__name__}: {exc}"
            state["updated_at"] = utc_now_iso()
            save_task_state(root, task_id, state)
        except Exception:
            traceback.print_exc()


def _spawn_framer_thread(root: Path, task_id: str) -> None:
    thread = threading.Thread(
        target=_run_framer_in_background,
        args=(root, task_id),
        name=f"framer-{task_id}",
        daemon=True,
    )
    thread.start()


def _load_framing_json(root: Path, task_id: str) -> dict[str, Any]:
    path = task_artifact_path(root, task_id, "framing.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Invalid framing.json: {exc}") from exc
    return data if isinstance(data, dict) else {}


def start_task(
    root: Path,
    raw_request: str,
    config_override: dict[str, Any] | None = None,
    code_path: str | None = None,
) -> dict[str, Any]:
    from .tasks import save_task_config, set_current_task_id

    request = raw_request.strip()
    if not request:
        raise WorkspaceError("Task request cannot be empty.")
    if not code_path or not str(code_path).strip():
        raise WorkspaceError("Code path is required.")
    resolved_path, display_path = _normalize_code_path(code_path)
    code_path_kind = "file" if resolved_path.is_file() else "directory"

    task_id = create_task_id(request)
    now = utc_now_iso()
    state = default_state()
    state["task_id"] = task_id
    if config_override:
        save_task_config(root, task_id, config_override)
    framing_ref = task_artifact_ref(task_id, "framing.md")
    state["title"] = request[:80]
    state["status"] = "FRAMING"
    state["current_phase"] = "framing"
    state["framing_running"] = True
    state["framing_error"] = None
    state["iteration"] = 0
    state["requires_human_approval"] = True
    state["goal"] = {
        "raw_request": request,
        "language": detect_language(request),
        "code_path": display_path,
        "code_path_kind": code_path_kind,
        "problem": None,
        "desired_outcome": None,
        "non_goals": [],
    }
    state["acceptance_criteria"] = []
    state["framing_questions"] = _initial_open_questions(request, None)
    state["phases"]["framing"]["status"] = "completed"
    state["phases"]["framing"]["artifact"] = framing_ref
    state["phases"]["framing_review"]["status"] = "waiting_for_review"
    state["phases"]["framing_review"]["artifact"] = framing_ref
    state["phases"]["investigation"]["artifact"] = task_artifact_ref(task_id, "research.md")
    state["phases"]["proposal"]["artifact"] = task_artifact_ref(task_id, "proposal.md")
    state["phases"]["test_authoring"]["artifact"] = task_artifact_ref(task_id, "test-plan.md")
    state["phases"]["testing"]["artifact"] = task_artifact_ref(task_id, "test-plan.md")
    state["agents"] = []
    state["updated_at"] = now

    task_artifact_path(root, task_id, "framing.md").parent.mkdir(parents=True, exist_ok=True)
    set_current_task_id(root, task_id)
    save_state(root, state)
    _spawn_framer_thread(root, task_id)
    return state


def submit_framing_answers(
    root: Path,
    task_id: str,
    answers: dict[str, str],
    by: str = "ui",
) -> dict[str, Any]:
    from .tasks import load_task_state, save_task_state

    state = load_task_state(root, task_id)
    if state.get("status") != "FRAMING_REVIEW":
        raise WorkspaceError(f"Cannot submit framing answers while status is {state.get('status')}.")
    questions = state.get("framing_questions") if isinstance(state.get("framing_questions"), list) else []
    for item in questions:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("id") or "")
        if qid in answers:
            item["answer"] = str(answers[qid]).strip()
    state["framing_questions"] = questions
    state.setdefault("framing_reviews", []).append(
        {"at": utc_now_iso(), "by": by, "answers": answers}
    )

    state["status"] = "FRAMING"
    state["current_phase"] = "framing"
    state["framing_running"] = True
    state["framing_error"] = None
    state["updated_at"] = utc_now_iso()
    save_task_state(root, task_id, state)
    _spawn_framer_thread(root, task_id)
    return state


def start_research(root: Path, task_id: str) -> dict[str, Any]:
    from .tasks import effective_config, load_task_state, save_task_state

    state = load_task_state(root, task_id)
    if state.get("status") != "FRAMING_REVIEW":
        raise WorkspaceError(f"Cannot start research while status is {state.get('status')}.")
    questions = state.get("framing_questions") if isinstance(state.get("framing_questions"), list) else []
    if not _ready_for_research(questions):
        raise WorkspaceError("Required framing questions must be answered before starting research.")

    config = effective_config(root, task_id)
    now = utc_now_iso()
    state["status"] = "INVESTIGATING"
    state["current_phase"] = "investigation"
    state["phases"]["framing_review"]["status"] = "completed"
    state["phases"]["investigation"]["status"] = "in_progress"
    state["updated_at"] = now
    save_task_state(root, task_id, state)

    # Investigator
    research_ref = task_artifact_ref(task_id, "research.md")
    prepare_investigator_prompt(root, state, mode=prompt_mode_for_role(state, config, "investigator"))
    if role_uses_manual(config, "investigator"):
        path = task_artifact_path(root, task_id, "research.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(draft_research(state), encoding="utf-8")
    record_agent_result(
        state,
        _run_role_with_session(root, state, config, "investigator", 0, [research_ref], task_id=task_id),
    )
    _post_role_handoff(root, state, config, "investigator", fallback_summary="Investigator produced research.md.")
    state["phases"]["investigation"]["status"] = "completed"
    state["status"] = "DESIGNING"
    state["current_phase"] = "proposal"
    state["phases"]["proposal"]["status"] = "in_progress"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, task_id, state)

    # Architect (pre-approval design pass)
    framing_ref = task_artifact_ref(task_id, "framing.md")
    proposal_ref = task_artifact_ref(task_id, "proposal.md")
    acceptance_ref = task_artifact_ref(task_id, "acceptance.md")
    acceptance_json_ref = task_artifact_ref(task_id, "acceptance.json")
    test_plan_ref = task_artifact_ref(task_id, "test-plan.md")
    prepare_architect_design_prompt(root, state, mode=prompt_mode_for_role(state, config, "architect"))
    if role_uses_manual(config, "architect"):
        request = state.get("goal", {}).get("raw_request") or state.get("title") or ""
        manual_criteria = draft_acceptance_items(request, acceptance_ref)
        task_artifact_path(root, task_id, "proposal.md").write_text(draft_proposal(state), encoding="utf-8")
        task_artifact_path(root, task_id, "acceptance.json").write_text(
            json.dumps({"acceptance_criteria": manual_criteria}, indent=2) + "\n", encoding="utf-8"
        )
        task_artifact_path(root, task_id, "acceptance.md").write_text(
            draft_acceptance(request, manual_criteria, framing_ref), encoding="utf-8"
        )
        # Stash criteria into state so the test-plan draft has them.
        state["acceptance_criteria"] = manual_criteria
        task_artifact_path(root, task_id, "test-plan.md").write_text(
            draft_test_plan_from_proposal(state), encoding="utf-8"
        )
    record_agent_result(
        state,
        _run_role_with_session(
            root,
            state,
            config,
            "architect",
            0,
            [proposal_ref, acceptance_ref, acceptance_json_ref, test_plan_ref],
            task_id=task_id,
        ),
    )
    _post_role_handoff(root, state, config, "architect", fallback_summary="Architect produced proposal, acceptance, and test plan.")
    state["acceptance_criteria"] = load_acceptance_criteria(
        task_artifact_path(root, task_id, "acceptance.json")
    )
    state["phases"]["proposal"]["status"] = "completed"
    state["phases"]["test_authoring"]["status"] = "ready_for_approval"
    state["phases"]["alignment"]["status"] = "waiting_for_approval"
    state["status"] = "WAITING_FOR_ALIGNMENT"
    state["current_phase"] = "alignment"
    state["requires_human_approval"] = True
    state["updated_at"] = utc_now_iso()
    save_task_state(root, task_id, state)
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
    state["runtime_input"] = _snapshot_runtime_input(root, tid)
    save_task_state(root, tid, state)
    return state


def _snapshot_runtime_input(root: Path, task_id: str) -> dict[str, Any]:
    """Capture the approval-time content (edited if present, else original) of
    design-package artifacts into a dict, so the implementer/tester loop reads
    from this snapshot rather than re-reading files mid-run. Also writes
    `*.approved.<ext>` copies for runtimes that need file paths."""
    artifacts_dir = root / ".agentloop" / "tasks" / task_id / "artifacts"
    snapshot: dict[str, Any] = {"captured_at": utc_now_iso(), "files": {}}
    bases = ["proposal.md", "acceptance.md", "acceptance.json", "test-plan.md", "research.md"]
    for base in bases:
        stem, dot, ext = base.rpartition(".")
        edited = artifacts_dir / (f"{stem}.edited.{ext}" if dot else f"{base}.edited")
        original = artifacts_dir / base
        chosen = edited if edited.exists() else original
        if not chosen.exists():
            continue
        try:
            text = chosen.read_text(encoding="utf-8")
        except Exception:
            continue
        approved = artifacts_dir / (f"{stem}.approved.{ext}" if dot else f"{base}.approved")
        approved.write_text(text, encoding="utf-8")
        snapshot["files"][base] = {
            "content": text,
            "source": "edited" if chosen is edited else "original",
            "path": chosen.resolve().relative_to(root.resolve()).as_posix(),
            "approved_path": approved.resolve().relative_to(root.resolve()).as_posix(),
        }
    return snapshot




def cancel_task(root: Path, cancelled_by: str = "requester", task_id: str | None = None) -> dict[str, Any]:
    from .tasks import load_task_state, resolve_task_id, save_task_state

    try:
        tid = resolve_task_id(root, task_id)
    except WorkspaceError:
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
    state["cancelled_from"] = status
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
    if status not in {"READY_TO_START", "IMPLEMENTING_AND_TESTING"}:
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
    state["status"] = "IMPLEMENTING_AND_TESTING"
    state["current_phase"] = "test_authoring"
    state["phases"]["test_authoring"]["status"] = "in_progress"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, tid, state)

    test_plan_ref = artifact_ref(state, "test-plan.md")
    prepare_role_prompt(
        root, state, "tester", iteration,
        mode="pre_implementation",
        session_mode=prompt_mode_for_role(state, config, "tester"),
    )
    record_agent_result(
        state,
        _run_role_with_session(root, state, config, "tester", iteration, [test_plan_ref], task_id=tid),
    )
    _post_role_handoff(root, state, config, "tester", fallback_summary="Tester drafted pre-implementation test plan.")
    state["phases"]["test_authoring"]["status"] = "completed"
    state["current_phase"] = "implementation"
    state["phases"]["implementation"]["status"] = "in_progress"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, tid, state)

    prepare_role_prompt(
        root, state, "implementer", iteration,
        session_mode=prompt_mode_for_role(state, config, "implementer"),
    )
    record_agent_result(state, _run_role_with_session(root, state, config, "implementer", iteration, [], task_id=tid))
    _post_role_handoff(root, state, config, "implementer", fallback_summary="Implementer applied approved changes.")
    # Detect silent runtime failure: implementer process exited cleanly but
    # produced no handoff JSON. Without this, tester/reviewer would keep seeing
    # an unchanged tree and bounce CHANGES_REQUIRED back to implementer until
    # max_iterations, wasting turns and obscuring the real failure.
    last_impl_log = next(
        (e for e in reversed(state.get("context_log") or [])
         if isinstance(e, dict) and e.get("role") == "implementer"),
        None,
    )
    if last_impl_log and not last_impl_log.get("handoff_present"):
        stderr_tail = _read_role_stderr_tail(root, state, "implementer")
        runtime_name = last_impl_log.get("runtime") or "?"
        state["status"] = "BLOCKED"
        state["current_phase"] = "blocked"
        state["phases"]["implementation"]["status"] = "blocked"
        state["blocked_reason"] = (
            f"Implementer ({runtime_name}) exited without writing handoff JSON "
            f"on iteration {iteration} (likely a silent runtime failure)."
            + (f"\n\nstderr tail:\n{stderr_tail}" if stderr_tail else "")
        )
        state["updated_at"] = utc_now_iso()
        save_task_state(root, tid, state)
        return state
    state["phases"]["implementation"]["status"] = "completed"
    state["current_phase"] = "testing"
    state["phases"]["testing"]["status"] = "in_progress"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, tid, state)

    test_results = run_test_commands(root, list(config.get("test_commands") or []), iteration, task_id=tid)
    prepare_role_prompt(
        root, state, "tester", iteration,
        mode="post_implementation",
        session_mode=prompt_mode_for_role(state, config, "tester"),
    )
    if role_uses_manual(config, "tester"):
        write_text(artifact_file(root, state, "test-plan.md"), draft_test_plan_with_results(state, test_results))
    record_agent_result(
        state,
        _run_role_with_session(root, state, config, "tester", iteration, [test_plan_ref], task_id=tid),
    )
    _post_role_handoff(root, state, config, "tester", fallback_summary="Tester recorded post-implementation evidence.")
    state["phases"]["testing"]["status"] = "completed"
    state["status"] = "REVIEWING"
    state["current_phase"] = "review"
    state["phases"]["review"]["status"] = "in_progress"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, tid, state)

    review_name = f"review-{iteration:03d}.json"
    review_ref = artifact_ref(state, review_name)
    review_path = artifact_file(root, state, review_name)
    prepare_role_prompt(
        root, state, "reviewer", iteration,
        review_name=review_name,
        session_mode=prompt_mode_for_role(state, config, "reviewer"),
    )
    if role_uses_manual(config, "reviewer"):
        review_data = manual_review(state, test_results)
        write_text(review_path, json.dumps(review_data, indent=2) + "\n")
    record_agent_result(
        state,
        _run_role_with_session(root, state, config, "reviewer", iteration, [review_ref], task_id=tid),
    )
    _post_role_handoff(root, state, config, "reviewer", fallback_summary="Reviewer wrote review JSON.")
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
        prepare_role_prompt(
            root, state, "integrator", iteration,
            session_mode=prompt_mode_for_role(state, config, "integrator"),
        )
        if role_uses_manual(config, "integrator"):
            write_text(artifact_file(root, state, "final-report.md"), draft_final_report(state, review))
        record_agent_result(
            state,
            _run_role_with_session(root, state, config, "integrator", iteration, [final_ref], task_id=tid),
        )
        _post_role_handoff(root, state, config, "integrator", fallback_summary="Integrator produced final report.")
    elif gate == "BLOCKED":
        state["status"] = "WAITING_FOR_HUMAN"
        state["current_phase"] = "human_review"
        state["requires_human_approval"] = True
    else:
        if iteration >= max_iterations:
            state["status"] = "BLOCKED"
            state["current_phase"] = "blocked"
        else:
            state["status"] = "IMPLEMENTING_AND_TESTING"
            state["current_phase"] = "test_authoring"
    state["updated_at"] = utc_now_iso()
    save_task_state(root, tid, state)
    return state


def run_task(root: Path, task_id: str | None = None) -> dict[str, Any]:
    from .tasks import load_task_state, resolve_task_id

    tid = resolve_task_id(root, task_id)
    state = load_task_state(root, tid)
    if state.get("status") not in {"READY_TO_START", "IMPLEMENTING_AND_TESTING"}:
        raise WorkspaceError(f"Cannot run while status is {state.get('status')}.")

    while state.get("status") in {"READY_TO_START", "IMPLEMENTING_AND_TESTING"}:
        previous_iteration = int(state.get("iteration") or 0)
        state = run_one_iteration(root, tid)
        if state.get("status") != "IMPLEMENTING_AND_TESTING":
            break
        if int(state.get("iteration") or 0) <= previous_iteration:
            raise WorkspaceError("Iteration did not advance; refusing to continue automatic loop.")
    return state
