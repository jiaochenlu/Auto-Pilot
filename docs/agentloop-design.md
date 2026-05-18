# AgentLoop Local Orchestrator Design

## 1. Background

AgentLoop is a local, standalone agent orchestration capability. It is inspired by Mars-style task, session, and role orchestration, but it must not depend on Mars, Mars MCP, or any Mars runtime.

AgentLoop must also be independent of any specific coding agent. Codex, Claude Code, GitHub Copilot CLI, or a custom local agent should all be usable through the same adapter contract.

The goal is to let a user submit a coding task once, then have a local supervisor drive the work through analysis, acceptance alignment, design, implementation, testing, review, and iterative refinement until the task is accepted or blocked. The supervisor owns the workflow; pluggable coding agents only execute role prompts.

This document is the implementation baseline for the first local version.

## 2. Goals

AgentLoop must support this workflow:

1. Analyze the submitted task.
2. Draft evaluation standards and acceptance criteria.
3. Ask the requester to confirm the goal and acceptance criteria.
4. Wait for an explicit start instruction.
5. Produce a design document.
6. Invoke role-based coding agents to work in parallel where safe.
7. Invoke a tester role to produce a test plan and implement test coverage.
8. Review the result against the acceptance criteria.
9. If the result does not pass, automatically loop from design to review.
10. Track status for every phase.

## 3. Non-Goals For MVP

The first version should avoid unnecessary platform work.

Non-goals:

- Web UI.
- Remote execution.
- Distributed task scheduling.
- Database-backed multi-user service.
- Full Mars compatibility.
- Dependence on a specific coding agent vendor.
- Complex permission marketplace.
- Automatic dependency installation without user approval.
- Unbounded infinite loops.

The MVP should be a local CLI plus a file-backed state machine.

## 4. System Shape

AgentLoop should be implemented as a command-line tool.

Example commands:

```powershell
agentloop init
agentloop start "Implement login flow"
agentloop status
agentloop approve
agentloop run
agentloop continue
agentloop review
```

High-level architecture:

```text
User
  -> AgentLoop CLI
  -> Workflow Engine
  -> State Store
  -> Universal Agent Runtime Adapter
  -> Local coding agents, such as Codex, Claude Code, Copilot, or custom agents
  -> Artifacts + tests + reviews
  -> Quality Gate
  -> Done or next iteration
```

## 5. Components

### 5.1 CLI Layer

The CLI is the user-facing entry point.

Responsibilities:

- Initialize `.agentloop/`.
- Create a task from a user request.
- Display task status.
- Record human approval.
- Trigger workflow execution.
- Resume an interrupted workflow.

Recommended implementation:

- Python.
- Typer for CLI commands.
- Pydantic for config and state validation.

### 5.2 Workflow Engine

The workflow engine owns the task state machine.

Responsibilities:

- Determine the current phase.
- Execute the next phase.
- Enforce human gates.
- Decide whether to advance, retry, block, or complete.
- Increment iteration count.
- Stop after `max_iterations`.

### 5.3 State Store

The MVP state store is JSON on disk.

Primary state file:

```text
.agentloop/state.json
```

The state file must be treated as the source of truth for phase status, acceptance criteria, active iteration, and review results.

### 5.4 Universal Agent Runtime Adapter

The runtime adapter invokes external coding agents through local commands or local APIs. This layer is the boundary that makes AgentLoop reusable across Codex, Claude Code, Copilot, and future agents.

It should expose one internal interface:

```text
run_agent(role, prompt_file, cwd, env, output_contract) -> AgentRunResult
```

The workflow engine must call only this interface. It must not know whether the backing agent is Codex, Claude Code, Copilot, or something else.

AgentLoop should ship with a generic command adapter first. The adapter receives a role prompt file and runs a configured command. Different agents can be configured per role.

Example config:

```json
{
  "default_runtime": "manual",
  "runtimes": {
    "manual": {
      "adapter": "manual"
    },
    "codex": {
      "command": "codex",
      "args": ["exec", "--prompt-file", "{prompt_file}"]
    },
    "claude-code": {
      "command": "claude",
      "args": ["--print", "--dangerously-skip-permissions", "{prompt_file}"]
    },
    "copilot": {
      "command": "gh",
      "args": ["copilot", "suggest", "--file", "{prompt_file}"]
    },
    "custom-shell-agent": {
      "command": "my-agent",
      "args": ["run", "--input", "{prompt_file}", "--cwd", "{cwd}"]
    }
  },
  "architect": { "runtime": "manual" },
  "implementer": { "runtime": "manual" },
  "tester": { "runtime": "manual" },
  "reviewer": { "runtime": "manual" }
}
```

The command examples above are illustrative. Exact CLI flags must be validated per installed agent. The generated default should be `manual` until the user selects an installed runtime. The durable AgentLoop contract is the role prompt input, artifact output, process exit status, logs, and optional structured JSON output.

Adapter responsibilities:

- Render placeholders such as `{prompt_file}`, `{cwd}`, `{role}`, `{iteration}`, and `{output_file}`.
- Start the agent process in the target workspace.
- Capture stdout, stderr, exit code, start time, and end time.
- Write role logs under `.agentloop/runs/<iteration>/`.
- Validate that required artifacts were produced.
- Validate structured output when a role requires JSON.

AgentLoop should support these adapter kinds over time:

```text
command: local shell command adapter for any CLI agent
stdio: long-running local process with stdin/stdout protocol
http: local HTTP service adapter
manual: writes prompt files and waits for the user to paste results
```

### 5.5 Artifact Manager

Every phase must produce durable artifacts. The orchestrator must not rely only on chat history.

Required artifacts:

```text
.agentloop/artifacts/analysis.md
.agentloop/artifacts/acceptance.md
.agentloop/artifacts/design.md
.agentloop/artifacts/test-plan.md
.agentloop/artifacts/review-001.json
.agentloop/artifacts/final-report.md
```

### 5.6 Quality Gate

The quality gate evaluates review output and decides the next state.

Inputs:

- Acceptance criteria.
- Test results.
- Review JSON.
- Current iteration count.

Outputs:

- `APPROVED`
- `CHANGES_REQUIRED`
- `BLOCKED`

### 5.7 Test Runner

The test runner executes configured local test commands.

Examples:

```json
{
  "test_commands": [
    "npm test",
    "pytest",
    "dotnet test"
  ]
}
```

MVP behavior:

- Run configured test commands sequentially.
- Capture stdout, stderr, exit code, and duration.
- Store logs under `.agentloop/runs/<iteration>/tests/`.
- Feed results into the reviewer prompt.

## 6. Directory Layout

AgentLoop stores all local orchestration data under `.agentloop/`.

```text
.agentloop/
|-- config.json
|-- state.json
|-- prompts/
|   |-- analysis.md
|   |-- acceptance.md
|   |-- architect.md
|   |-- implementer.md
|   |-- tester.md
|   `-- reviewer.md
|-- artifacts/
|   |-- analysis.md
|   |-- acceptance.md
|   |-- design.md
|   |-- test-plan.md
|   |-- review-001.json
|   `-- final-report.md
|-- runs/
|   `-- 001/
|       |-- architect.log
|       |-- implementer.log
|       |-- tester.log
|       |-- reviewer.log
|       `-- tests/
`-- locks/
```

## 7. State Machine

AgentLoop should use explicit task states.

```text
CREATED
  -> ANALYZING
  -> CRITERIA_DRAFTED
  -> WAITING_FOR_ALIGNMENT
  -> READY_TO_START
  -> DESIGNING
  -> IMPLEMENTING_AND_TESTING
  -> REVIEWING
  -> DONE
```

Failure and waiting states:

```text
WAITING_FOR_HUMAN
BLOCKED
CANCELLED
```

Review transition rules:

```text
REVIEWING + APPROVED -> DONE
REVIEWING + CHANGES_REQUIRED -> DESIGNING
REVIEWING + BLOCKED -> WAITING_FOR_HUMAN
iteration > max_iterations -> BLOCKED
```

The loop should be bounded. Default:

```text
max_iterations = 7
```

## 8. State File Schema

Initial schema:

```json
{
  "schema_version": 1,
  "task_id": "20260518-150000-login-flow",
  "title": "Implement login flow",
  "status": "WAITING_FOR_ALIGNMENT",
  "current_phase": "alignment",
  "iteration": 0,
  "max_iterations": 7,
  "requires_human_approval": true,
  "goal": {
    "raw_request": "Implement login flow",
    "problem": null,
    "desired_outcome": null,
    "non_goals": []
  },
  "acceptance_criteria": [],
  "phases": {
    "analysis": {
      "status": "pending",
      "artifact": ".agentloop/artifacts/analysis.md"
    },
    "alignment": {
      "status": "pending",
      "approved_by": null,
      "approved_at": null
    },
    "design": {
      "status": "pending",
      "artifact": ".agentloop/artifacts/design.md"
    },
    "implementation": {
      "status": "pending"
    },
    "testing": {
      "status": "pending",
      "artifact": ".agentloop/artifacts/test-plan.md"
    },
    "review": {
      "status": "pending",
      "last_review": null
    }
  },
  "agents": [],
  "created_at": "2026-05-18T15:00:00+08:00",
  "updated_at": "2026-05-18T15:00:00+08:00"
}
```

## 9. Acceptance Criteria Model

Acceptance criteria should be structured, not free text only.

```json
{
  "id": "AC-1",
  "description": "User can log in with valid credentials.",
  "verification": "automated_test",
  "required": true,
  "status": "pending",
  "evidence": null
}
```

Valid `verification` values:

```text
automated_test
manual_check
static_review
document_review
```

Valid `status` values:

```text
pending
passed
failed
waived
```

## 10. Human Gates

There are two required human gates.

### 10.1 Alignment Gate

After analysis and acceptance drafting, the workflow must stop in `WAITING_FOR_ALIGNMENT`.

The user must review:

- `.agentloop/artifacts/analysis.md`
- `.agentloop/artifacts/acceptance.md`

Then run:

```powershell
agentloop approve
```

### 10.2 Start Gate

After approval, the task moves to `READY_TO_START`.

Execution starts only when the user runs:

```powershell
agentloop run
```

## 11. Role Model

MVP roles:

```text
analyst
architect
implementer
tester
reviewer
integrator
```

Role responsibilities:

```text
analyst
- Understand request
- Identify gaps and assumptions
- Draft initial acceptance criteria

architect
- Produce design.md
- Define file ownership boundaries
- Define test strategy

implementer
- Implement scoped code changes
- Respect file ownership boundaries
- Avoid unrelated refactors

tester
- Produce test-plan.md
- Add or update tests
- Run configured test commands where possible

reviewer
- Compare result against acceptance criteria
- Emit review JSON
- Assign severity to issues

integrator
- Resolve conflicts between role outputs
- Run final validation
- Produce final-report.md
```

## 12. Agent Input And Output Contract

AgentLoop must integrate with coding agents through files and process metadata, not through vendor-specific conversation state.

Every agent run receives:

```text
prompt_file: path to the rendered role prompt
cwd: workspace root
role: analyst, architect, implementer, tester, reviewer, or integrator
iteration: current iteration number
output_contract: required artifacts and structured output rules
```

Every agent run returns:

```json
{
  "role": "architect",
  "runtime": "claude-code",
  "command": "...",
  "exit_code": 0,
  "started_at": "2026-05-18T15:00:00+08:00",
  "ended_at": "2026-05-18T15:01:00+08:00",
  "stdout_log": ".agentloop/runs/001/architect.stdout.log",
  "stderr_log": ".agentloop/runs/001/architect.stderr.log",
  "artifacts": [".agentloop/artifacts/design.md"],
  "structured_output": null
}
```

AgentLoop considers an agent run successful only when:

- The process exits successfully, unless the runtime is configured to tolerate non-zero exits.
- Required artifacts exist.
- Required JSON outputs parse and pass schema validation.
- The run did not request a blocked or unsafe operation.

Agents may differ in how they receive prompts, but they must converge on the same filesystem artifacts. This is what makes AgentLoop reusable by Copilot, Claude Code, Codex, or any future agent.

## 13. Runtime Configuration Model

AgentLoop should separate role assignment from runtime definition.

Runtime definition describes how to call an agent:

```json
{
  "name": "codex",
  "adapter": "command",
  "command": "codex",
  "args": ["exec", "--prompt-file", "{prompt_file}"],
  "env": {},
  "timeout_seconds": 3600
}
```

Role assignment describes which runtime handles each role:

```json
{
  "roles": {
    "analyst": { "runtime": "claude-code" },
    "architect": { "runtime": "claude-code" },
    "implementer": { "runtime": "codex" },
    "tester": { "runtime": "codex" },
    "reviewer": { "runtime": "claude-code" },
    "integrator": { "runtime": "codex" }
  }
}
```

This allows one workflow to mix agents deliberately. For example, Claude Code can handle design and review, Codex can handle implementation, and Copilot can handle targeted code suggestions.

MVP should include a `manual` runtime for agents that cannot be invoked cleanly from a CLI:

```text
1. AgentLoop writes the role prompt to `.agentloop/prompts/<role>.md`.
2. AgentLoop tells the user where to paste it.
3. The user saves the agent's result into the required artifact path.
4. AgentLoop validates the artifact and continues.
```

## 14. Parallel Execution Policy

Parallel implementation is allowed only when ownership boundaries are explicit.

Safe example:

```text
implementer-api owns: src/api/**, tests/api/**
implementer-ui owns: src/ui/**, tests/ui/**
tester owns: tests/**, .agentloop/artifacts/test-plan.md
```

If boundaries are unclear, MVP should run implementation serially and allow tester planning in parallel.

Default MVP policy:

```text
analysis: serial
acceptance: serial
design: serial
implementation: serial by default
testing: can run after or alongside implementation planning
review: serial
```

Parallel workers can be added after the single-agent loop is reliable.

## 15. Review JSON Schema

Reviewer output must be machine-readable JSON.

```json
{
  "decision": "CHANGES_REQUIRED",
  "summary": "Implementation is close, but negative login tests are missing.",
  "open_medium_high_count": 1,
  "comments": [
    {
      "id": "R-1",
      "severity": "high",
      "area": "tests",
      "text": "Missing test coverage for invalid credentials.",
      "required_action": "Add an automated test for invalid login.",
      "status": "open"
    }
  ],
  "acceptance_results": [
    {
      "criteria_id": "AC-1",
      "status": "passed",
      "evidence": "login.spec.ts passed"
    },
    {
      "criteria_id": "AC-2",
      "status": "failed",
      "evidence": "No invalid-login test found"
    }
  ],
  "test_results": [
    {
      "command": "npm test",
      "exit_code": 0,
      "log": ".agentloop/runs/001/tests/npm-test.log"
    }
  ]
}
```

Valid decisions:

```text
APPROVED
CHANGES_REQUIRED
BLOCKED
```

Severity policy:

```text
low: does not block approval
medium: blocks approval
high: blocks approval
```

Approval rule:

```text
APPROVED requires:
- zero open medium issues
- zero open high issues
- every required acceptance criterion is passed or explicitly waived
- configured tests pass, unless waived by the requester
```

## 16. Iteration Algorithm

Pseudo-flow:

```text
start task
run analysis
draft acceptance criteria
wait for human approval
wait for start command

while iteration < max_iterations:
    iteration += 1
    run architect
    run implementer
    run tester
    run tests
    run reviewer

    if reviewer.decision == APPROVED:
        run integrator final report
        mark DONE
        exit

    if reviewer.decision == BLOCKED:
        mark WAITING_FOR_HUMAN
        exit

    feed review comments into next design prompt
    continue

mark BLOCKED
request human decision
```

## 17. Prompt Strategy

Prompts should be generated from templates plus current task state.

Each role prompt should include:

- Current task goal.
- Acceptance criteria.
- Current iteration number.
- Relevant previous artifacts.
- File ownership rules.
- Required output files.
- Explicit stop conditions.

The reviewer prompt must require JSON-only output for the review artifact.

## 18. Permissions And Safety

MVP must be conservative.

Allowed by default:

- Reading files.
- Writing under `.agentloop/`.
- Running configured test commands.

Requires user approval:

- Installing dependencies.
- Network access.
- Deleting files.
- Git reset, checkout, clean, force push.
- Editing files outside the current workspace.
- Running unknown shell commands outside configured allowlist.

The first version can enforce this through documentation and command configuration. A later version can add command interception.

## 19. CLI Command Design

### `agentloop init`

Creates `.agentloop/` with default config and prompt templates.

### `agentloop start "<task>"`

Creates a new task state, runs analysis and acceptance drafting, then stops at `WAITING_FOR_ALIGNMENT`.

### `agentloop status`

Prints current task status, phase, iteration, and next action.

### `agentloop approve`

Marks the alignment gate as approved and moves to `READY_TO_START`.

### `agentloop run`

Starts or resumes the automated loop.

### `agentloop continue`

Continues after a recoverable stop.

### `agentloop review`

Runs reviewer only against current artifacts and code state.

### `agentloop cancel`

Marks the task as `CANCELLED`.

## 20. Implementation Plan

Build in small increments.

### Phase 1: Local State Foundation

- Create Python package skeleton.
- Add CLI entry point.
- Add `.agentloop/` initializer.
- Add runtime config model for reusable agent backends.
- Add generic command adapter interface without binding to one coding agent.
- Add Pydantic models for config, state, phase, acceptance criteria, and review.
- Add JSON read/write helpers.

Exit criteria:

- `agentloop init` creates the expected directory layout and default runtime config.
- `agentloop status` can read and print state.

### Phase 2: Analysis And Alignment

- Implement `agentloop start`.
- Generate initial analysis and acceptance prompt files.
- Invoke analyst agent through the configured runtime adapter.
- Store `analysis.md` and `acceptance.md`.
- Stop at `WAITING_FOR_ALIGNMENT`.
- Implement `agentloop approve`.

Exit criteria:

- User can create a task and approve acceptance criteria.

### Phase 3: Single-Agent Execution Loop

- Implement architect, implementer, tester, reviewer sequence.
- Add test command execution.
- Parse review JSON.
- Implement gate decision logic.
- Loop on `CHANGES_REQUIRED`.

Exit criteria:

- One local task can go from approved to done or blocked.

### Phase 4: Final Report

- Add integrator role.
- Generate `final-report.md`.
- Include artifacts, tests, review result, and residual risks.

Exit criteria:

- `DONE` tasks always have a final report.

### Phase 5: Safe Parallelism

- Add file ownership model.
- Allow multiple implementer roles only when ownership is explicit.
- Run independent agents concurrently.
- Detect overlapping ownership declarations before execution.

Exit criteria:

- Parallel workers can run without touching overlapping file scopes.

## 21. Open Design Questions

These can be decided during implementation:

1. Should the initial generated config prefer a manual runtime or ask the user to choose an installed runtime?
2. Should `agentloop start` run analysis through an agent, or generate a draft locally first?
3. Should test commands be auto-detected from project files or configured manually?
4. Should review JSON be strict JSON only, or allow markdown with embedded JSON?
5. Should multiple active tasks be supported in one workspace for MVP?

Recommended MVP answers:

1. Generate a configurable runtime file and require the user to select or confirm the runtime before first execution.
2. Use an agent for analysis.
3. Start with manual config, add detection later.
4. Require strict JSON for reviewer output.
5. Support one active task per workspace.

## 22. MVP Success Criteria

The MVP is successful when:

- A user can initialize AgentLoop in a local repo.
- The same workflow can run through any configured coding agent runtime that satisfies the file-based contract.
- A task produces analysis and acceptance artifacts.
- The workflow pauses for user approval.
- The workflow starts only after explicit user command.
- The design, implementation, testing, and review phases produce durable artifacts.
- Review can trigger an automatic redesign/retry loop.
- The loop stops at `DONE`, `BLOCKED`, or `max_iterations`.
- `agentloop status` accurately reports the current phase and next action.

## 23. Multi-Task Lifecycle, Per-Task Config, and Batch Operations

This section supersedes the "one active task per workspace" assumption from §21.5.

### 23.1 Storage layout

```
.agentloop/
  config.json                  # global defaults
  state.json                   # legacy pointer + mirror of the current task's state
  tasks/<task_id>/
    state.json                 # AUTHORITATIVE per-task state
    config.json                # NEW: optional per-task overrides
    artifacts/...
  runs/<task_id>/<NNN>/        # NEW: per-task namespaced run logs
    <role>.stdout.log
    <role>.stderr.log
    tests/NN-test.log
  locks/<task_id>.lock         # NEW: per-task lock file (JSON payload)
```

`tasks migrate` (also lazily invoked on every command) copies legacy global state
into the per-task directory and moves legacy `runs/NNN/` directories under the
current task when discovered.

### 23.2 Source of truth

`agentloop/tasks.py` owns per-task discovery and IO:

- `list_task_ids(root)` / `active_task_ids(root)`
- `load_task_state(root, task_id)` / `save_task_state(root, task_id, state)`
- `effective_config(root, task_id)` — see §23.4
- `resolve_task_id(root, explicit)` — explicit > single-active > error with a
  candidate list (used by every lifecycle CLI command)
- `select_task_ids(root, task_ids=..., all_tasks=..., statuses=...)` — selector
  for batch commands; exactly one mode must be used

`workspace.save_state` writes to the per-task file when the state has a `task_id`
and mirrors to the legacy global `state.json` only when it matches the current
task pointer. This keeps `agentloop status` and external tooling working without
clobbering concurrent task state.

### 23.3 Concurrency and locking

`agentloop/locks.py` exposes `task_lock(root, task_id, blocking=...)`. The lock
file at `.agentloop/locks/<task_id>.lock` holds JSON `{pid, started_at, host,
task_id}`. Defaults:

- `run <id>` acquires non-blocking and fails fast with `task <id> is locked by
  pid <X> on <host> since <ts>` (exit code 2). Pass `--wait` to block.
- Stale locks (recorded pid not alive) are reclaimed automatically.
- `agentloop tasks unlock <id>` is the operator override.

There is **no global lock**: two `run` invocations against different task ids
never contend.

### 23.4 Per-task configuration

`.agentloop/tasks/<id>/config.json` is a sparse overlay. Precedence:

1. per-task override (`tasks/<id>/config.json`)
2. global config (`.agentloop/config.json`)
3. built-in defaults (`models.default_config()`)

Override-capable keys:

- `test_commands` — replaces the global list
- `max_iterations` — positive int
- `default_runtime` — must exist in the global `runtimes` registry
- `roles.<role>.runtime` — per-role overlay, merged key by key

The runtime registry itself (`runtimes`) is not per-task overridable in this
iteration; per-task config selects among already-registered runtimes.

### 23.5 CLI surface

Single-task lifecycle commands accept an optional positional `<task_id>` and
`--task-id <id>`. When omitted, the resolver picks the single active task or
errors with a list of candidates.

- `agentloop status [<task_id>]`
- `agentloop start "<task>"`
- `agentloop approve [<task_id>] [--by NAME]`
- `agentloop cancel [<task_id>] [--by NAME]`
- `agentloop run [<task_id>] [--wait]`

The `tasks` subgroup gains inventory, batch, config, lock, and migration
commands:

- `agentloop tasks list [--status STATUS] [--json]`
- `agentloop tasks delete <id>` / `tasks delete-all`
- `agentloop tasks unlock <id>`
- `agentloop tasks migrate`
- `agentloop tasks approve <selector> [--by NAME]`
- `agentloop tasks cancel <selector> [--by NAME]`
- `agentloop tasks run <selector> [--wait] [--parallel N]`
- `agentloop tasks config show <id> [--effective]`
- `agentloop tasks config set <selector> <key> <value> [--json]`
- `agentloop tasks config unset <selector> <key>`
- `agentloop tasks config clear <selector>`

`<selector>` is exactly one of: `--task-id ID` (repeatable), `--all`,
`--status STATUS` (repeatable). All batch commands print a per-task summary
(`ok` / `error <message>`); per-task failures never abort the rest of the batch
and the exit code is non-zero only if at least one task failed.

`tasks run --parallel N` uses a thread pool; the lock model carries the
concurrency guarantee.
