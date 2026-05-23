# Analysis

## Goal

Build a usable UI product shape for AgentLoop centered on task management. The UI should let a user create, view, update, and delete AgentLoop tasks, inspect each task's latest lifecycle progress, and read the latest runtime/test return output without needing to manually browse `.agentloop` files or run CLI status commands.

The product should feel like a local task operations console for AgentLoop: a task list for scanning work, a detail view for one task, explicit lifecycle controls, editable task configuration where appropriate, and runtime output panels that expose the most recent role/test results.

## Non-Goals

- Do not implement remote/cloud orchestration, multi-user collaboration, authentication, or hosted deployment unless later requested.
- Do not replace the existing AgentLoop workflow engine or runtime adapter model.
- Do not invent a separate task storage system when the existing `.agentloop/tasks/<task_id>/state.json`, `config.json`, artifacts, and `.agentloop/runs/` files are the source of truth.
- Do not require users to understand the full AgentLoop internal lifecycle before they can manage tasks.
- Do not add generic dashboard features that are not tied to task CRUD, progress, lifecycle control, or runtime output visibility.

## Assumptions

- The first UI can be local-first and workspace-scoped, consistent with AgentLoop's file-backed design.
- Existing CLI/workflow functions can be reused behind the UI for creating tasks, approving/canceling/running tasks, deleting tasks, and reading task snapshots.
- A task's latest progress can be derived from `state.json` fields such as `status`, `current_phase`, `iteration`, `max_iterations`, `requires_human_approval`, `phases`, `updated_at`, and `acceptance_criteria`.
- Runtime returns are available through `state.agents` plus stdout/stderr log files under `.agentloop/runs/<task_id>/<iteration>/`, and test command output is available under `.agentloop/runs/<task_id>/<iteration>/tests/`.
- The UI does not need real-time streaming in the first pass if it can refresh and show the latest persisted state and logs after workflow actions complete.
- CRUD means create task, read/list task details, update task metadata/configuration where AgentLoop already supports safe updates, and delete tasks.

## Risks

- Long-running `agentloop run` calls may block a simple web request if the UI invokes workflow execution synchronously.
- Reading logs directly from disk can expose very large outputs; the UI should truncate, paginate, or otherwise bound displayed content.
- Concurrent CLI and UI operations could race on the same task; the UI should respect existing task locks and show lock/error states clearly.
- Delete operations are destructive because they remove task state and artifacts; the UI needs confirmation and clear task identity before deletion.
- Editing task state directly would be risky; updates should use existing task config and workflow APIs instead of arbitrary JSON mutation.
- Existing task artifacts may be missing or malformed, so the UI must degrade gracefully when state, config, artifacts, or logs are unavailable.

## Open Questions

- Should the UI be implemented as a Python-served local web app inside the existing package, a static frontend with a small local API, or another product form?
- Should `run` actions execute synchronously with a loading state, or should the UI introduce background execution/job tracking?
- Which task fields should be user-editable beyond per-task config: title, raw request, max iterations, test commands, role runtime overrides, or only config fields already supported by the CLI?
- Should runtime output show only the latest role/test logs, or provide an iteration/role log history browser?
- Should task creation immediately call `start_task` and produce analysis/acceptance artifacts, matching CLI behavior, or create a draft task before analysis?
- What level of visual verification is expected for the UI: unit tests only, local browser smoke test, or screenshot-based checks?
