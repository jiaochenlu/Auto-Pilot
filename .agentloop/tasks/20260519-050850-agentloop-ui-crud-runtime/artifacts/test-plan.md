# Test Plan: AgentLoop Task Console UI

## Scope

Validate the AgentLoop UI product surface for task management:

- Task CRUD through the local JSON API used by the browser UI.
- Task list/detail view models for status, phase, iteration, current task, and malformed task handling.
- Latest runtime output exposure, including agent stdout/stderr and test logs.
- Artifact previews and bounded artifact reads.
- Per-task configuration updates from the UI.
- HTTP server routing for static UI assets and API endpoints.

## Automated Coverage

Reviewed `tests/test_ui_api.py`; no additional test edits were needed for this iteration because the file already covers the UI/API contract for CRUD, runtime output, structured test results, and HTTP routing.

Key coverage includes:

- `test_http_ui_endpoints_back_task_crud_and_static_assets` starts the real `AgentLoopUIHandler` on an ephemeral localhost port and verifies static HTML serving, task create/list/config/delete flows, and delete confirmation failure.
- `test_task_list_marks_current_and_handles_malformed_state` verifies current-task marking and malformed task-state resilience.
- `test_create_task_uses_workflow_artifacts` verifies task creation produces workflow artifacts: `analysis.md`, `acceptance.md`, and `acceptance.json`.
- `test_detail_includes_artifacts_runtime_and_test_logs` verifies detail payloads expose artifacts, latest iteration, agent stdout, and test log content.
- `test_detail_merges_structured_test_result_metadata` verifies runtime test logs merge structured metadata from review artifacts, including command, exit code, and duration.
- `test_detail_includes_structured_test_result_with_missing_log` verifies structured test results still render when the referenced test log is missing.
- `test_patch_config_and_delete_task` verifies direct config patch and delete behavior.
- `test_actions_reflect_status` verifies action enablement for approval and run states.

## Commands Run

```powershell
python -m unittest tests.test_ui_api -v
```

Result: passed, 8 tests.

```powershell
python -m unittest discover -s tests -v
```

Result: passed, 58 tests.

## Evidence

Focused UI/API run:

```text
Ran 8 tests in 2.626s
OK
```

Full suite run:

```text
Ran 58 tests in 23.460s
OK
```

HTTP integration evidence from the focused and full-suite runs included successful live requests:

```text
GET / HTTP/1.1 200
POST /api/tasks HTTP/1.1 201
GET /api/tasks HTTP/1.1 200
PATCH /api/tasks/20260519-054224-manage-ui-tasks/config HTTP/1.1 200
DELETE /api/tasks/20260519-054224-manage-ui-tasks HTTP/1.1 400
DELETE /api/tasks/20260519-054224-manage-ui-tasks HTTP/1.1 200
```

## Manual Verification Recommended

- Start the UI with `python -m agentloop --root . ui --port 8765` and verify the browser workflow visually.
- Create a task, search/filter it, update config, inspect artifacts, inspect runtime logs, and delete it.
- Check responsive layout at a narrow viewport because the automated tests validate API/server behavior, not CSS layout.

## Residual Risk

The automated coverage verifies the data contract and HTTP routes behind the UI, but it does not run a Playwright browser interaction against the static JavaScript. Browser-level coverage should be added if this UI becomes a larger surface or if regressions appear in DOM event wiring, dialogs, filters, or responsive layout.
