# Design - AgentLoop Task Console UI

Task: Build a UI for AgentLoop focused on task management, including CRUD, latest task progress, and runtime returns.
Iteration: 2
Task artifact directory: `.agentloop/tasks/20260519-050850-agentloop-ui-crud-runtime/artifacts/`

## 1. Decision

Use the existing **AgentLoop Task Console** product shape: a local, workspace-scoped web app served by AgentLoop itself.

The implementation should remain a lightweight Python HTTP server plus static HTML/CSS/vanilla JS. AgentLoop's file-backed `.agentloop/` layout remains the source of truth. The UI is an operations console, not a landing page: the first screen shows task inventory, selected-task progress, lifecycle controls, editable safe config, artifacts, and runtime/test output.

Iteration 2 should not redesign the product from scratch. The current code already has the correct major shape:

- `agentloop/ui.py`: local HTTP server and static file serving.
- `agentloop/api.py`: JSON API and view-model builders.
- `agentloop/logs.py`: safe bounded artifact/log readers.
- `agentloop/ui_static/index.html`, `styles.css`, `app.js`: static console UI.
- `tests/test_ui_api.py`: temp-workspace coverage for task list/detail, CRUD, runtime logs, and HTTP endpoints.

The main design correction for this iteration is to close AC-9: local test command output must expose structured metadata (`command`, `exit_code`, `duration_ms`) in addition to bounded log content.

## 2. Product Model

AgentLoop Task Console is a local task operations surface for one workspace.

Core jobs:

- See all AgentLoop tasks and identify the current one.
- Create a task from a raw request using existing AgentLoop start behavior.
- Read task status, phase, iteration progress, approval requirement, acceptance criteria, artifacts, runtime returns, and test returns.
- Update allowlisted task configuration, specifically `max_iterations` and `test_commands` for this iteration.
- Approve, run/resume, cancel, and delete tasks through validated workflow APIs.
- Diagnose recent runtime behavior without opening `.agentloop/runs/` manually.

The UI should optimize for repeated operational use: dense scanning, direct controls, clear disabled-action reasons, and bounded log panes.

## 3. Current Architecture

### 3.1 Server

`agentloop/ui.py` serves static assets and routes JSON endpoints under `/api`.

Required routes:

- `GET /api/tasks`
- `POST /api/tasks`
- `GET /api/tasks/<task_id>`
- `PATCH /api/tasks/<task_id>/config`
- `DELETE /api/tasks/<task_id>`
- `POST /api/tasks/<task_id>/approve`
- `POST /api/tasks/<task_id>/cancel`
- `POST /api/tasks/<task_id>/run`
- `GET /api/tasks/<task_id>/artifacts/<name>`

The server should keep binding to `127.0.0.1` by default. It must not serve arbitrary workspace files.

### 3.2 API/View Models

`agentloop/api.py` owns UI-facing view models and should keep domain mutation delegated to existing AgentLoop modules.

Important functions:

- `build_task_list(root)`
- `build_task_detail(root, task_id)`
- `available_actions(state, lock_reason=None)`
- `list_task_artifacts(root, task_id)`
- `latest_runtime_summary(root, state)`
- `create_task(root, payload)`
- `patch_task_config(root, task_id, payload)`
- `delete_task(root, task_id, payload)`
- `approve_task_api(root, task_id, payload)`
- `cancel_task_api(root, task_id, payload)`
- `run_task_api(root, task_id, payload)`
- `read_artifact(root, task_id, name)`

This split is appropriate. Keep API functions small, typed around dictionaries, and testable without starting the HTTP server.

### 3.3 Frontend

The current static frontend uses a two-panel operations layout:

- Sidebar: task list, status filter, search, create task.
- Main panel: selected task header, lifecycle actions, tabs for Overview, Artifacts, Config, Runtime.

This is the right product shape. Continue with a restrained operations-console visual direction: neutral surfaces, semantic status accents, stable row heights, scrollable log panes, and no marketing/hero content.

## 4. Data Contracts

### 4.1 Task List

`GET /api/tasks` returns:

```json
{
  "current_task_id": "20260519-050850-agentloop-ui-crud-runtime",
  "tasks": [
    {
      "task_id": "...",
      "title": "...",
      "status": "WAITING_FOR_ALIGNMENT",
      "current_phase": "alignment",
      "iteration": 0,
      "max_iterations": 7,
      "updated_at": "...",
      "current": true,
      "locked": false,
      "error": null
    }
  ]
}
```

Malformed task states must still render as rows with `status: "UNKNOWN"` and an error message.

### 4.2 Task Detail

`GET /api/tasks/<task_id>` returns:

```json
{
  "state": {
    "task_id": "...",
    "title": "...",
    "status": "READY_TO_START",
    "current_phase": "design",
    "iteration": 1,
    "max_iterations": 7,
    "requires_human_approval": false,
    "goal": {},
    "acceptance_criteria": [],
    "phases": {},
    "created_at": "...",
    "updated_at": "..."
  },
  "config": {
    "override": {},
    "effective": {}
  },
  "actions": {
    "approve": { "enabled": false, "reason": "status is READY_TO_START" },
    "run": { "enabled": true, "reason": null },
    "cancel": { "enabled": true, "reason": null },
    "delete": { "enabled": true, "reason": null },
    "config": { "enabled": true, "reason": null }
  },
  "artifacts": [],
  "runtime": {
    "iterations": [0, 1],
    "latest_iteration": 1,
    "agents": [],
    "tests": []
  },
  "errors": []
}
```

Only selected safe state fields should be returned. Do not expose arbitrary file contents through the detail payload.

## 5. Runtime Output Design

Runtime output has two categories: agent runtime returns and local test command returns.

### 5.1 Agent Runtime Returns

Continue deriving latest agent returns from `state.agents` for the latest iteration.

Each agent entry should include:

```json
{
  "role": "tester",
  "runtime": "manual",
  "adapter": "...",
  "command": "...",
  "exit_code": 0,
  "duration_ms": 1234,
  "artifacts": [],
  "stdout": {
    "path": ".agentloop/runs/<task_id>/001/tester.stdout.log",
    "exists": true,
    "missing": false,
    "truncated": false,
    "bytes_total": 12,
    "bytes_returned": 12,
    "content": "..."
  },
  "stderr": {
    "path": ".agentloop/runs/<task_id>/001/tester.stderr.log",
    "exists": true,
    "missing": false,
    "truncated": false,
    "bytes_total": 0,
    "bytes_returned": 0,
    "content": ""
  }
}
```

Missing stdout/stderr logs should be represented as data, not thrown as fatal detail errors.

### 5.2 Local Test Command Returns

AC-9 requires the test output view to show command, exit code, duration, and log content. The current implementation only scans `*.log` files and returns `{ name, log }`, which is not enough.

Iteration 2 should update the runtime contract so every test entry has this shape:

```json
{
  "name": "01-test.log",
  "command": "python -m unittest discover -s tests",
  "exit_code": 0,
  "duration_ms": 24172,
  "log": {
    "path": ".agentloop/runs/<task_id>/001/tests/01-test.log",
    "exists": true,
    "missing": false,
    "truncated": false,
    "bytes_total": 4096,
    "bytes_returned": 4096,
    "content": "COMMAND\npython -m unittest discover -s tests\n\nSTDOUT\n..."
  }
}
```

Recommended source priority:

1. Prefer structured `test_results` from review artifacts when available, especially `review-*.json` files containing entries with `command`, `exit_code`, `duration_ms`, and `summary`.
2. Prefer structured test result data from workflow state if a future implementation stores it there.
3. Fall back to scanning `.agentloop/runs/<task_id>/<iteration>/tests/*.log` and parse the `COMMAND` section for `command`; use `null` for `exit_code` and `duration_ms` when no structured source exists.

This fallback keeps existing log-only workspaces readable while making the UI honest when metadata is unavailable.

### 5.3 Review Artifact Correlation

To satisfy AC-9 for completed review runs, `latest_runtime_summary` should attempt to load latest review JSON artifacts for the selected task.

Suggested helper behavior:

- Look under `.agentloop/tasks/<task_id>/artifacts/` for files matching `review-*.json`.
- Sort by filename descending and/or modified time descending.
- Parse the newest valid JSON object.
- If it contains a `test_results` list, index entries by command and/or log filename when possible.
- Attach matching structured metadata to logs in `.agentloop/runs/<task_id>/<latest_iteration>/tests/`.
- If a structured result has no matching log file, still return a test entry with metadata and a missing-log payload.

Do not fail the whole task detail if a review JSON file is malformed. Add a recoverable error only if useful.

## 6. UI Behavior

### 6.1 Runtime Tab

The Runtime tab should render both agent entries and test entries in a shared tab list.

Agent entries display:

- Role label.
- Runtime.
- Command.
- Exit code.
- Duration.
- Produced artifact list when present.
- Stdout and stderr panes.

Test entries display:

- Test log name.
- Command.
- Exit code, with `unknown` when unavailable.
- Duration, with `unknown` when unavailable.
- Bounded log pane.
- Truncation indicator when applicable.

For test metadata, the frontend must not rely on command text embedded inside the log. It should render `selected.data.command`, `selected.data.exit_code`, and `selected.data.duration_ms` when present.

### 6.2 Empty And Missing States

Use precise empty states:

- `No runtime output for this iteration.` when there are no agents and no tests.
- `No test output for this iteration.` if the selected category is tests and no test entries exist.
- `Missing test log` when structured metadata exists but the log file is absent.
- `Exit unknown` and `Duration unknown` when only log fallback is available.

### 6.3 CRUD And Lifecycle

Keep current interactions:

- Create task dialog posts `{ "request": "..." }`.
- Config tab saves `max_iterations` and `test_commands`.
- Delete dialog requires typing the full task id.
- Approve, Run, Cancel buttons call mutation endpoints and refresh detail/list afterward.

Disabled actions must continue to include a `title`/reason from the server-side action model.

## 7. Safety

Safety rules remain unchanged:

- Bind to `127.0.0.1` by default.
- Use existing `task_lock` for mutations.
- Delete only after exact id confirmation.
- Resolve task, artifact, and log paths under their expected directories.
- Bound artifact and log reads to 64 KiB by default.
- Allow config edits only for supported keys.
- Do not add arbitrary state JSON editing.

When parsing review artifacts, read only files under `.agentloop/tasks/<task_id>/artifacts/` and ignore malformed JSON gracefully.

## 8. Implementation Plan For Iteration 2

### Phase 1 - Test Metadata View Model

- Add a helper in `agentloop/api.py` to collect latest structured test results from review artifacts.
- Update `latest_runtime_summary` so `runtime.tests[]` returns `name`, `command`, `exit_code`, `duration_ms`, and `log`.
- Preserve compatibility with log-only workspaces by returning `null` metadata when unavailable.

### Phase 2 - Frontend Rendering

- Update `agentloop/ui_static/app.js` test rendering to display command, exit code, duration, truncation state, and log content from structured fields.
- Keep existing runtime tab layout; no broad CSS redesign required.

### Phase 3 - Tests

- Update `tests/test_ui_api.py::test_detail_includes_artifacts_runtime_and_test_logs` to assert structured test metadata.
- Add coverage for fallback log-only tests where metadata is unavailable.
- Add coverage for structured review artifact `test_results` with a matching or missing test log.
- Run `python -m unittest tests.test_ui_api -v` and `python -m unittest discover -s tests -v`.

## 9. Acceptance Mapping

- AC-1: covered by task list API and sidebar rendering.
- AC-2: covered by `POST /api/tasks` calling `start_task`.
- AC-3: covered by detail payload and Overview/Artifacts tabs.
- AC-4: covered by `PATCH /api/tasks/<id>/config` for `max_iterations` and `test_commands`.
- AC-5: covered by exact-confirm delete and safe task path resolution.
- AC-6: covered by server-side action availability and lifecycle endpoints.
- AC-7: covered by refreshed detail/list after lifecycle mutations.
- AC-8: covered by agent runtime entries with stdout/stderr bounded logs.
- AC-9: iteration 2 must close this by returning and rendering structured local test metadata.
- AC-10: covered by malformed state handling, bounded reads, and missing-log payloads; preserve this while adding metadata parsing.
- AC-11: covered by temp-workspace API tests; extend for AC-9.
- AC-12: covered by console-first UI structure.

## 10. Open Questions

- Should future versions store `test_results` directly in task state to avoid reconstructing metadata from review artifacts? Recommendation: yes, but not required for this iteration.
- Should `run` become a background job with progress polling? Recommendation: defer; synchronous v1 is acceptable while the workflow engine remains synchronous.
- Should runtime history expose older iterations in the UI? Recommendation: keep latest-first now; add iteration selector later if users need historical debugging.
