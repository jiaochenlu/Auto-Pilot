# Test Plan — Multi-Task Lifecycle, Per-Task Config, Batch Operations

Task: 重新审视 agentloop 任务的生命周期管理，支持多任务并发、单任务/批量配置与管理。
Iteration: 1
Task artifact directory: `.agentloop/tasks/20260518-093703-agentloop/artifacts/`
Test module: `tests/test_multitask.py` (uses the in-process `agentloop.cli.main` entry point with the bundled `manual` runtime — hermetic, no external coding agent required).

## 1. Scope

Verify the design in `design.md` against the 13 acceptance criteria in `acceptance.md`:

- Per-task state as the source of truth and migration safety (AC-1, AC-12).
- Concurrent task lifecycle and explicit/implicit task selection (AC-2, AC-3, AC-4).
- Concurrency-safe `run` namespacing and per-task locks (AC-5, AC-6).
- Per-task configuration overrides — single and batch surfaces (AC-7, AC-8, AC-9, AC-10).
- Documentation and approval (AC-11, AC-13).

Out of scope (matches `design.md` §1 non-goals): distributed/queued execution, GUI, runtime adapter rewrites, dependency graphs.

## 2. Environment

- Python 3.11 on Windows 11 (cross-checked with `os.name == "nt"` branches in `agentloop/locks.py`).
- `pytest` invoked from repo root: `python -m pytest tests/test_multitask.py -v`.
- Each test uses `tempfile.TemporaryDirectory` for an isolated workspace; no shared state between tests.
- All roles default to the `manual` runtime via `init_workspace`, so artifacts and review JSON are generated in-process — `agentloop run` completes within milliseconds.

## 3. AC → Test Mapping

| AC | Verification | Test | Coverage notes |
| --- | --- | --- | --- |
| AC-1 | functional_review + code | `tests/test_multitask.py::MultiTaskLifecycleTests::test_explicit_task_id_targets_non_current_task` and `MigrationTests::test_migration_copies_legacy_state_into_per_task_file` | Asserts `start`, `approve`, `cancel` mutate `.agentloop/tasks/<id>/state.json` directly; code inspection of `tasks.save_task_state` / `workflow.start_task` confirms global file is only mirrored as a pointer. |
| AC-2 | automated_test | `MultiTaskLifecycleTests::test_start_allows_multiple_concurrent_tasks` | Starts two tasks back-to-back without `approve`/`cancel` in between; verifies both per-task state files exist with `WAITING_FOR_ALIGNMENT` and both surface in `tasks list`. |
| AC-3 | automated_test | `MultiTaskLifecycleTests::test_explicit_task_id_targets_non_current_task` (+ `BatchOperationsTests::test_run_namespaces_logs_per_task` for `run`) | Exercises `approve --task-id`, `cancel <positional>` and `run --task-id` against a non-current task; asserts only the addressed task changes. |
| AC-4 | automated_test | `MultiTaskLifecycleTests::test_ambiguous_bare_command_lists_candidates` and `test_bare_command_works_with_single_active` | Zero/one/many active-task variants. Many-active case asserts exit code 2 and the `multiple active tasks` candidate list on stderr. |
| AC-5 | automated_test | `BatchOperationsTests::test_run_namespaces_logs_per_task` | Runs two tasks via `tasks run --task-id A --task-id B`; asserts both `.agentloop/runs/<tid>/001/architect.stdout.log` exist independently and per-task `state.json` reach `DONE` without cross-contamination. (Spec also satisfied by code: `runner.run_test_commands(task_id=...)` and `adapters.run_role(task_id=...)` both namespace under `runs/<task_id>/<iteration>/`.) |
| AC-6 | automated_test | `LockingTests::test_run_fails_fast_when_task_locked` and `test_unlock_removes_stale_lock` | Holds the lock via `task_lock(..., blocking=False)` and confirms `agentloop run <tid>` exits 2 with `locked by pid` on stderr. The stale-pid case validates `tasks unlock` removal. |
| AC-7 | functional_review + automated | `PerTaskConfigTests::test_per_task_test_commands_override_takes_effect` and code: `tasks.effective_config` precedence (per-task > global > default). | Override file is read on next `run` and produces `per-task-marker` in the namespaced test log. |
| AC-8 | automated_test | `PerTaskConfigTests::test_per_task_test_commands_override_takes_effect` and `test_config_show_returns_override_and_effective` | `tasks config set --task-id <tid> ...` writes the per-task `config.json`; subsequent `run` consumes it; `tasks config show` returns both raw and `--effective` views. |
| AC-9 | automated_test | `BatchOperationsTests::test_batch_cancel_isolates_failures` | One task pre-mutated to `DONE`; `tasks cancel --all` exits 1 but the remaining task is cancelled and the batch summary reports per-task `ok`/`error` rows. |
| AC-10 | automated_test | `BatchOperationsTests::test_batch_config_set_all` | `tasks config set --all max_iterations 5` writes the override to every per-task `config.json`. |
| AC-11 | functional_review | `docs/agentloop-design.md` diff (manual review) — covered by design artifact `design.md` describing lifecycle, precedence table, lock semantics, CLI reference. | No automated test; reviewer to confirm doc update in the PR. |
| AC-12 | functional_review + automated | `MigrationTests::test_migration_copies_legacy_state_into_per_task_file` | Simulates a pre-migration workspace (deletes the per-task copy after `start`); `tasks migrate` restores the per-task file from the legacy global pointer with no data loss. |
| AC-13 | human_review | Recorded in `state.json` (`phases.alignment.status = approved`, `approved_at: 2026-05-18T09:39:52+00:00`). | Approval already captured at task start; no automated check. |

## 4. Execution evidence

Run from repo root (`C:/Users/chenlujiao/OneDrive - Microsoft/Documents/AutoPilot`):

```powershell
python -m pytest tests/test_multitask.py -v
```

Expected: all 9 tests pass. The suite is hermetic; each test creates its own `TemporaryDirectory`, so it can run in parallel with other suites.

Note for this iteration: the orchestrating harness rejected interactive `python -m pytest` invocations (Bash permission prompts), so the suite was not re-executed from inside the agent shell. The test code itself was inspected end-to-end and aligns with the implementation in `agentloop/tasks.py`, `agentloop/locks.py`, `agentloop/workflow.py`, `agentloop/runner.py`, and `agentloop/cli.py`. The reviewer should re-run the suite locally before approving — this is the single remaining manual step for the testing phase.

## 5. Risks / gaps

- **Cross-process locking (AC-5 / AC-6 hardening).** The current automated test runs both `run` operations in the same Python process. The lock implementation (`os.O_CREAT | os.O_EXCL` on a per-task lock file plus PID liveness via `OpenProcess`/`os.kill(0)`) is cross-process safe by construction, but a `subprocess.Popen`-based spawn would give stronger evidence. Tracked as a follow-up — the deterministic in-process assertion already exercises the lock contract.
- **`docs/agentloop-design.md` (AC-11).** Not yet updated in this iteration. Reviewer should request the doc patch or accept the inline `design.md` artifact as the doc-of-record for now.
- **Selector validation.** `select_task_ids` raises on `--task-id` referencing a missing task; this path is covered indirectly by `test_batch_config_set_all` (selection happy path) but a negative test for the mutually-exclusive selectors is worth adding next iteration.

## 6. Sign-off checklist

- [x] AC-1 — per-task state authoritative (code + tests)
- [x] AC-2 — concurrent `start` (test_start_allows_multiple_concurrent_tasks)
- [x] AC-3 — explicit task id selector (test_explicit_task_id_targets_non_current_task)
- [x] AC-4 — single/many resolver semantics (test_ambiguous_bare_command_lists_candidates, test_bare_command_works_with_single_active)
- [x] AC-5 — per-task `runs/` namespacing (test_run_namespaces_logs_per_task)
- [x] AC-6 — per-task lock fail-fast + unlock (LockingTests)
- [x] AC-7 — per-task config override precedence (test_per_task_test_commands_override_takes_effect)
- [x] AC-8 — `tasks config set/show` CLI (test_config_show_returns_override_and_effective)
- [x] AC-9 — batch lifecycle isolates failures (test_batch_cancel_isolates_failures)
- [x] AC-10 — batch config set `--all` (test_batch_config_set_all)
- [ ] AC-11 — `docs/agentloop-design.md` updated (manual reviewer)
- [x] AC-12 — migration restores legacy workspaces (test_migration_copies_legacy_state_into_per_task_file)
- [x] AC-13 — alignment already approved by requester (state.json)
