# Task Analysis

## Raw Request

重新审视一下当前 agentloop 的任务的生命周期管理，考虑多多任务并发的情况，实现更好的单任务配置和单任务管理，也允许用户进行批量配置和批量管理。

## Current Behavior (as observed in code)

- Single active task. `agentloop/workspace.py` keeps one global `.agentloop/state.json`; `start_task` refuses unless status is in `{CREATED, CANCELLED, DONE}` (`workflow.py:411`). Only one task can be in `WAITING_FOR_ALIGNMENT / DESIGNING / ... / REVIEWING` at any moment.
- Task lifecycle commands (`start`, `approve`, `cancel`, `run`) all act on the implicit current task — none of them accept a `task_id`.
- Per-task artifacts already live in `.agentloop/tasks/<task_id>/artifacts/` and a per-task `state.json` snapshot is written on save (`workspace.save_state`), so per-task storage is partly in place but not the source of truth.
- Configuration is global only. `.agentloop/config.json` holds one `runtimes`/`roles`/`test_commands`/`max_iterations` set shared by every task. There is no per-task override.
- `agentloop tasks list/delete/delete-all` exists for inventory, but batch operations on lifecycle (start/approve/cancel/run several at once) or batch config edits do not exist.
- `run_one_iteration` mutates the global state file, so two concurrent runs would race on `.agentloop/state.json` and on the un-namespaced `.agentloop/runs/<iteration>/tests/` directory (`runner.py:13`).

## Goal

Redesign the task lifecycle so multiple AgentLoop tasks can coexist and progress independently, with first-class per-task configuration and management, plus batch operations layered on top.

Concretely:

1. Make the per-task directory the source of truth for state; remove the "one active task" constraint.
2. Add a per-task config layer (overrides on runtimes/roles/test_commands/max_iterations) that falls back to global defaults.
3. Make every lifecycle CLI command address tasks by `task_id` (with a sensible default when there is exactly one active task, for backwards compatibility).
4. Support safe concurrent execution of `run` for different tasks (per-task lock; per-task `runs/` namespace).
5. Add batch commands for both management (`tasks approve|cancel|run --all|--filter`) and configuration (`tasks config set ...`, `--all` / multi-id).

## Non-Goals

- Distributed execution or running tasks on remote machines.
- A new GUI or web dashboard.
- Rewriting the runtime adapters (`adapters.py`) or the review-gate logic (`quality.py`).
- Changing artifact schemas (`acceptance.json`, review JSON) or the phase model.
- Cross-task dependency graphs / task chaining.

## Assumptions

- Existing single-task workspaces must keep working: after upgrade, `agentloop status / approve / run` with no `task_id` should still target the existing task if there is exactly one active one.
- Concurrency is in-process and same-machine (Python threads or separate `agentloop run <id>` processes), not a job queue.
- Per-task locks can be file-based under `.agentloop/locks/<task_id>.lock`; the directory is already created by `ensure_workspace`.
- Manual runtime stays the default; nothing here forces a real coding agent.
- Acceptable to deprecate (but not yet remove) the implicit "current task" pointer in `.agentloop/state.json`; we can keep it as a convenience pointer.

## Risks

- **State migration.** Existing workspaces have data in the global `state.json` but possibly no per-task snapshot for older tasks. Need a one-shot migration path or a tolerant loader.
- **Race conditions.** Two `run` invocations on the same task must not interleave phase writes; locks must be acquired before any state mutation, not just at the CLI boundary.
- **Test command isolation.** `runner.run_test_commands` writes to `.agentloop/runs/<iteration>/tests/`, which collides across tasks. Needs `.agentloop/runs/<task_id>/<iteration>/`.
- **Config precedence confusion.** Per-task overrides plus global defaults plus role-level runtime assignment is three layers; needs a clearly documented merge order to avoid surprising users.
- **Batch blast radius.** `tasks run --all` or `tasks cancel --all` are destructive-feeling; need dry-run / confirmation, and per-task failures must not abort the whole batch.
- **CLI compatibility.** Changing argument shapes (e.g. requiring `task_id`) breaks scripts. Prefer additive flags with a single-active-task fallback.

## Open Questions

1. **Default active task.** When only one task is active, should bare `agentloop run` keep working, or should we always require `--task-id` / a `agentloop use <id>` selector?
2. **Concurrency model.** Is the expectation that users launch multiple `agentloop run <id>` processes themselves, or do we want a built-in `agentloop tasks run --all --parallel N` that spawns workers?
3. **Per-task config surface.** Which fields should be per-task overridable — just `test_commands` and `max_iterations`, or also `roles` runtime assignment and `default_runtime`?
4. **Batch filter language.** For batch ops, is filtering by status (`--status WAITING_FOR_ALIGNMENT`) enough, or do we need tag/label support on tasks?
5. **Migration.** Should the first `agentloop` invocation after upgrade auto-migrate the global `state.json` into the matching per-task directory, or require an explicit `agentloop tasks migrate`?
6. **Lock semantics.** If a lock file is stale (process crashed), do we auto-break it, require `--force`, or expose `agentloop tasks unlock <id>`?
7. **Scope of this task.** Does the requester want all of: lifecycle refactor + per-task config + batch ops in one shot, or should we land them in stages (and if staged, which stage first)?
