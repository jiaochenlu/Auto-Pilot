# Acceptance Criteria

## Task

重新审视 agentloop 任务生命周期管理，支持多任务并发、单任务级别的配置/管理，以及批量配置/管理。

## Draft Criteria

| ID | Required | Verification | Criterion | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| AC-1 | yes | functional_review | Per-task state is the source of truth: `.agentloop/tasks/<task_id>/state.json` is read/written directly by all lifecycle operations; the global `.agentloop/state.json` no longer gates whether a new task can be started. | pending | code inspection of workspace.py + workflow.start_task |
| AC-2 | yes | automated_test | `agentloop start` can be invoked while another task is in any non-terminal state (e.g. `WAITING_FOR_ALIGNMENT` or `DESIGNING`); the new task is created without error and both tasks appear in `agentloop tasks list` with their independent statuses. | pending | new pytest covering two-concurrent-starts scenario |
| AC-3 | yes | automated_test | Lifecycle commands accept a `--task-id <id>` (or positional `<id>`) selector — `agentloop approve`, `agentloop cancel`, `agentloop run`, `agentloop status` — and act on that task only, regardless of which task is the "current" one. | pending | pytest covering each command with explicit task_id |
| AC-4 | yes | automated_test | When exactly one task is active, lifecycle commands without `--task-id` keep working against that task (backwards compatibility); when zero or multiple are active, the CLI errors with a message that lists candidate task_ids. | pending | pytest for zero/one/many active-task cases |
| AC-5 | yes | automated_test | Two `agentloop run <task_id_a>` and `agentloop run <task_id_b>` invocations against different tasks can execute without corrupting each other's `state.json`, artifacts, or `runs/` logs. Test command output is namespaced under `.agentloop/runs/<task_id>/<iteration>/`. | pending | pytest spawning two concurrent runs against manual runtime |
| AC-6 | yes | automated_test | A per-task lock prevents two concurrent `run` invocations on the same `task_id` from interleaving; the second invocation either waits or fails fast with a clear "task is locked by pid X" error. | pending | pytest acquiring lock then attempting second run |
| AC-7 | yes | functional_review | Per-task config overrides exist: `.agentloop/tasks/<task_id>/config.json` (or equivalent) may override `test_commands`, `max_iterations`, and role→runtime assignments. Merge order is documented: per-task override > global config > built-in default. | pending | code + docs for per-task config loader |
| AC-8 | yes | automated_test | A CLI surface for single-task configuration exists, e.g. `agentloop tasks config set <task_id> <key> <value>` and `agentloop tasks config show <task_id>`, and changes are reflected on the next `agentloop run <task_id>`. | pending | pytest setting a per-task override and observing effect |
| AC-9 | yes | automated_test | Batch lifecycle commands exist for at least: approve, cancel, run. They accept either explicit ids (`--task-id` repeatable), `--all`, or `--status <STATUS>` filtering. Per-task failures are reported individually and do not abort the remaining batch. | pending | pytest covering batch with one failing task |
| AC-10 | yes | automated_test | Batch configuration commands exist: a single `tasks config set` invocation can target multiple task_ids (`--task-id` repeated, `--all`, or `--status`) and apply the same override to each. | pending | pytest applying override to multiple tasks |
| AC-11 | yes | functional_review | Documentation (`docs/agentloop-design.md` or a new doc) is updated to describe the new multi-task lifecycle, per-task config precedence, batch operations, and concurrency/locking model. | pending | doc diff review |
| AC-12 | yes | functional_review | Existing single-task workspaces continue to work after upgrade: either via automatic migration on first command, or via a documented `agentloop tasks migrate` command. No data loss for the existing task. | pending | manual upgrade walkthrough on a sample workspace |
| AC-13 | yes | human_review | Requester reviews and approves the task-specific analysis and acceptance criteria before execution starts. | pending | .agentloop/tasks/20260518-093703-agentloop/artifacts/analysis.md |

## Approval Instruction

Review this file together with `.agentloop/tasks/20260518-093703-agentloop/artifacts/analysis.md`. The open questions there (especially Q3 on which config fields are per-task overridable, and Q7 on staged vs. single-shot delivery) materially affect the scope above — please respond to them at approval time so the criteria can be tightened or trimmed.

If the scope is correct, run:

```powershell
python -m agentloop approve
```
