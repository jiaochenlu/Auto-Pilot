# AgentLoop User Guide

This guide shows how to use AgentLoop as a local coding-agent workflow runner.

AgentLoop is file-backed. It keeps global configuration under `.agentloop/config.json`, and each task under:

```text
.agentloop/tasks/<task_id>/
  state.json
  config.json          optional per-task override
  artifacts/
```

## 1. Initialize A Workspace

Run this once in the repository root:

```powershell
python -m agentloop init
```

Recommended for a new user: initialize and detect local coding-agent CLIs in one step.

```powershell
python -m agentloop init --detect-runtimes
```

If the workspace already has runtime entries and you want detection to replace them:

```powershell
python -m agentloop init --detect-runtimes --replace-runtimes
```

Detection writes found runtimes into `.agentloop/config.json`, but it does not assign them to roles. You still choose which runtime each role should use.

Check the workspace:

```powershell
python -m agentloop status
python -m agentloop tasks
```

A new workspace starts with no active task:

```text
status: CREATED
```

## 2. Configure Runtimes

A runtime is the command AgentLoop uses for a role such as `analyst`, `architect`, `implementer`, `tester`, `reviewer`, or `integrator`.

Recommended first-time setup:

```powershell
python -m agentloop init --detect-runtimes
python -m agentloop runtime list
python -m agentloop runtime assign-all claude-code
python -m agentloop runtime verify claude-code --timeout-seconds 120
```

Use `codex` instead of `claude-code` if that is the runtime you want for every role.

List current runtimes and role assignments:

```powershell
python -m agentloop runtime list
```

Detect locally installed runtime commands:

```powershell
python -m agentloop runtime detect
```

Replace existing detected entries:

```powershell
python -m agentloop runtime detect --replace
```

Detection looks for common commands such as Claude Code, Codex, and GitHub Copilot CLI. On Windows it also checks common npm install locations under `%APPDATA%\npm`.

Detected runtimes are not enabled automatically. After detection, choose one of these patterns.

Use one runtime for every role:

```powershell
python -m agentloop runtime assign-all claude-code
```

Use different runtimes for different roles:

```powershell
python -m agentloop runtime assign analyst claude-code
python -m agentloop runtime assign architect claude-code
python -m agentloop runtime assign implementer codex
python -m agentloop runtime assign tester claude-code
python -m agentloop runtime assign reviewer claude-code
python -m agentloop runtime assign integrator claude-code
```

Then verify the selected runtime can write artifacts:

```powershell
python -m agentloop runtime verify claude-code --timeout-seconds 120
```

Add a built-in preset:

```powershell
python -m agentloop runtime add-preset claude-code --replace
python -m agentloop runtime add-preset codex --replace
python -m agentloop runtime add-preset manual --replace
```

Set the default runtime:

```powershell
python -m agentloop runtime set-default claude-code
```

## 3. Start A Task

Start creates a task id, invokes the `analyst` runtime, and stops before execution.

```powershell
python -m agentloop start "实现 doctor 命令，检查 workspace 状态并输出 PASS/FAIL"
```

The analyst must produce task-specific artifacts:

```text
.agentloop/tasks/<task_id>/artifacts/analysis.md
.agentloop/tasks/<task_id>/artifacts/acceptance.md
.agentloop/tasks/<task_id>/artifacts/acceptance.json
```

Review them before approving:

```powershell
python -m agentloop tasks
Get-Content .agentloop\tasks\<task_id>\artifacts\analysis.md
Get-Content .agentloop\tasks\<task_id>\artifacts\acceptance.md
```

## 4. Approve Or Cancel

Approve starts execution eligibility. It does not run the task yet.

```powershell
python -m agentloop approve --task-id <task_id>
```

Equivalent positional form:

```powershell
python -m agentloop approve <task_id>
```

Cancel a task:

```powershell
python -m agentloop cancel --task-id <task_id>
```

If exactly one task is active, `--task-id` can be omitted:

```powershell
python -m agentloop approve
python -m agentloop cancel
```

If multiple tasks are active, AgentLoop asks for an explicit task id.

## 5. Configure A Task

Task config overrides global config for one task only.

Show a task's config:

```powershell
python -m agentloop tasks config show --task-id <task_id>
```

Set test commands. Use `--json` for arrays:

```powershell
python -m agentloop tasks config set --task-id <task_id> --json test_commands '["python -m unittest discover -s tests"]'
```

Set max iterations:

```powershell
python -m agentloop tasks config set --task-id <task_id> max_iterations 5
```

Set role runtimes for one task:

```powershell
python -m agentloop tasks config set --task-id <task_id> roles.analyst.runtime claude-code
python -m agentloop tasks config set --task-id <task_id> roles.implementer.runtime codex
python -m agentloop tasks config set --task-id <task_id> roles.reviewer.runtime claude-code
```

Remove one override:

```powershell
python -m agentloop tasks config unset --task-id <task_id> max_iterations
```

Clear all overrides for a task:

```powershell
python -m agentloop tasks config clear --task-id <task_id>
```

Config precedence is:

```text
per-task config > global .agentloop/config.json > built-in defaults
```

## 6. Run A Task

Run executes the design, implementation, testing, review, and integration loop.

```powershell
python -m agentloop run --task-id <task_id>
```

AgentLoop automatically loops when the quality gate returns `CHANGES_REQUIRED`:

```text
design -> implementation -> testing -> review -> changes required -> next iteration
```

The loop stops when one of these happens:

```text
DONE
BLOCKED
WAITING_FOR_HUMAN
max_iterations reached
```

Run and wait for an existing task lock instead of failing fast:

```powershell
python -m agentloop run --task-id <task_id> --wait
```

## 7. Quality Gate

The reviewer writes `review-<iteration>.json`, but the quality gate makes the final decision.

A review cannot pass if:

- any required acceptance criterion is not `passed` or `waived`
- `open_medium_high_count` is greater than `0`
- any test result has `exit_code` other than `0`
- a required automated/unit/test criterion exists but no executed passing test is reported

This means `exit_code: null` is not accepted as passing test evidence.

## 8. Inspect Results

List tasks:

```powershell
python -m agentloop tasks
python -m agentloop tasks list
```

Show one task status:

```powershell
python -m agentloop status --task-id <task_id>
```

Important artifacts:

```text
.agentloop/tasks/<task_id>/artifacts/design.md
.agentloop/tasks/<task_id>/artifacts/test-plan.md
.agentloop/tasks/<task_id>/artifacts/review-001.json
.agentloop/tasks/<task_id>/artifacts/final-report.md
```

Run logs are namespaced per task:

```text
.agentloop/runs/<task_id>/<iteration>/
```

## 9. Batch Operations

Approve multiple tasks:

```powershell
python -m agentloop tasks approve --task-id <id1> --task-id <id2>
```

Cancel by status:

```powershell
python -m agentloop tasks cancel --status WAITING_FOR_ALIGNMENT
```

Run every ready task one at a time:

```powershell
python -m agentloop tasks run --status READY_TO_START
```

Run with limited parallelism:

```powershell
python -m agentloop tasks run --status READY_TO_START --parallel 2
```

Preview selection without acting:

```powershell
python -m agentloop tasks run --status READY_TO_START --dry-run
```

Apply the same config to many tasks:

```powershell
python -m agentloop tasks config set --status WAITING_FOR_ALIGNMENT max_iterations 5
```

## 10. Delete Tasks

Delete one task:

```powershell
python -m agentloop tasks delete <task_id>
```

Delete all tasks and reset current state:

```powershell
python -m agentloop tasks delete-all
```

Alias:

```powershell
python -m agentloop tasks clear
```

Runtime configuration is preserved.

## 11. Locks And Migration

If a task lock is stale, unlock it:

```powershell
python -m agentloop tasks unlock <task_id>
```

Run migration manually. It is idempotent:

```powershell
python -m agentloop tasks migrate
```

## 12. Recommended First Test

Use a small task with clear tests:

```powershell
python -m agentloop start "为 AgentLoop 增加 doctor 命令：python -m agentloop doctor。要求：检查 .agentloop 是否初始化、config.json 是否可解析、state.json 是否可解析、当前 task artifact 目录是否存在、配置的 test_commands 是否是列表；输出每项检查的 PASS/FAIL；如果任何检查失败，命令退出码为 2；添加单元测试覆盖全部通过、缺少 config、非法 state JSON、artifact 目录缺失、test_commands 类型错误。"
```

Then:

```powershell
python -m agentloop tasks
Get-Content .agentloop\tasks\<task_id>\artifacts\acceptance.md
python -m agentloop tasks config set --task-id <task_id> --json test_commands '["python -m unittest discover -s tests"]'
python -m agentloop approve --task-id <task_id>
python -m agentloop run --task-id <task_id>
```

## 13. Troubleshooting

If `start` fails because a runtime cannot write artifacts, verify the runtime:

```powershell
python -m agentloop runtime verify claude-code --timeout-seconds 120
```

If a command is ambiguous, list active tasks and pass `--task-id`:

```powershell
python -m agentloop tasks
python -m agentloop run --task-id <task_id>
```

If tests are not executed, configure `test_commands` before `run`:

```powershell
python -m agentloop tasks config set --task-id <task_id> --json test_commands '["python -m unittest discover -s tests"]'
```

If you want to restart from zero while keeping runtime config:

```powershell
python -m agentloop tasks delete-all
```
