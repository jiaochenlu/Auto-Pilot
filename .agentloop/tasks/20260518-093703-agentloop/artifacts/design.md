# Design — Multi-Task Lifecycle, Per-Task Config, Batch Operations

Task: 重新审视 agentloop 任务的生命周期管理，支持多任务并发、单任务级别的配置/管理以及批量配置/管理。
Iteration: 1
Task artifact directory: `.agentloop/tasks/20260518-093703-agentloop/artifacts/`

## 1. Goals (mapped to acceptance criteria)

- Per-task `state.json` becomes the source of truth (AC-1, AC-12).
- `start` is no longer gated by a global active-task slot; many tasks can coexist (AC-2).
- Every lifecycle command can address a specific task by id, with a sensible default when exactly one task is active (AC-3, AC-4).
- Concurrent `run` against different tasks is safe; same-task `run` is mutually excluded with a per-task lock (AC-5, AC-6).
- Per-task config overrides exist with a documented precedence and a CLI surface (AC-7, AC-8).
- Batch lifecycle and batch config commands exist, with per-task isolation of failures (AC-9, AC-10).
- Documentation is updated (AC-11).

Non-goals (per analysis): distributed/queued execution, GUI, runtime adapter rewrites, dependency graphs.

## 2. Storage layout

```
.agentloop/
  config.json                 # global defaults (unchanged shape)
  state.json                  # demoted: pointer to current_task_id only
  tasks/<task_id>/
    state.json                # AUTHORITATIVE per-task state (already partially written)
    config.json               # NEW: per-task overrides (optional)
    artifacts/...              # existing
  runs/<task_id>/<iteration>/  # NEW: per-task namespacing for test logs
    tests/NN-test.log
  locks/<task_id>.lock         # NEW: per-task lock file (pid + started_at JSON)
  prompts/                     # unchanged role prompt templates
```

Migration is performed lazily on first command after upgrade (see §8). The global `state.json` is rewritten into a minimal pointer form:

```json
{ "schema_version": 2, "current_task_id": "<id-or-null>" }
```

Any task-scoped fields still found in the legacy global file are moved into `tasks/<current_task_id>/state.json` if the per-task file does not already exist.

## 3. Source-of-truth model

A new module `agentloop/tasks.py` owns task discovery and per-task IO. Public functions:

- `list_task_ids(root) -> list[str]` — sorted directory listing under `.agentloop/tasks/`.
- `load_task_state(root, task_id) -> dict` — reads `.agentloop/tasks/<id>/state.json`.
- `save_task_state(root, task_id, state) -> None` — writes per-task file then refreshes the global pointer if `current_task_id == task_id` (or if no pointer is set).
- `task_config_path(root, task_id) -> Path`.
- `effective_config(root, task_id) -> dict` — merge order: per-task override > global `config.json` > `default_config()`.
- `active_task_ids(root) -> list[str]` — filters out `CREATED`, `CANCELLED`, `DONE`.
- `resolve_task_id(root, explicit: str | None) -> str` — explicit > single-active fallback > error listing candidates (AC-4 message contract).

`workspace.save_state` is reworked: when the state has a `task_id`, write **only** `.agentloop/tasks/<id>/state.json`. The legacy global file is updated only with the `current_task_id` pointer, never the full state. `workspace.load_state` becomes a thin shim used only by `cmd_status`/legacy callers; everything else reads through `tasks.load_task_state`.

`workflow.start_task` is refactored:

1. Generate `task_id = create_task_id(raw_request)`.
2. Build a fresh `default_state()` in memory (no global gate).
3. Write `.agentloop/tasks/<task_id>/state.json` directly.
4. Update the global pointer optimistically (`current_task_id = <new_id>`) — purely a convenience for bare commands; it does not block AC-2.

`workflow.approve_task`, `cancel_task`, `run_task`, `run_one_iteration` all take an explicit `task_id` and operate on `load_task_state` / `save_task_state`. The current single-task entry points are kept as thin wrappers that call `resolve_task_id(root, None)`.

## 4. Concurrency and locking

- Per-task lock file at `.agentloop/locks/<task_id>.lock` is acquired by `run` (and by destructive lifecycle ops on the same task: `approve`, `cancel`, `tasks config set`).
- Locking uses `msvcrt.locking` on Windows and `fcntl.flock` on POSIX, with the same `agentloop/locks.py` helper exposing a context manager `task_lock(root, task_id, *, blocking: bool, stale_after_seconds: int | None)`.
- The lock file payload is JSON `{ "pid": int, "started_at": iso8601, "host": str }` written under the lock, so a second invocation can render a clear `task <id> is locked by pid <X> since <ts>` error (AC-6).
- Default behavior for `run <id>`: non-blocking acquire → fail fast with the descriptive error; a `--wait` flag switches to blocking.
- Stale-lock detection: if the recorded `pid` is not running and `stale_after_seconds` has elapsed, the lock helper logs a warning and reclaims the lock. An explicit `agentloop tasks unlock <id>` command is exposed for the operator override.
- **Important: there is no global lock.** Two `run` invocations on **different** task_ids never contend, because every state mutation, every config read, and every runs/ write is per-task scoped (AC-5).

## 5. Per-task configuration

`.agentloop/tasks/<id>/config.json` is a sparse overlay; absent keys fall through to the global config. Override-capable keys (Q3 decision, conservative scope):

- `test_commands` — replaces the global list when present (not appended).
- `max_iterations` — integer override.
- `roles` — partial dict; each entry is merged key by key, so `{"roles": {"reviewer": {"runtime": "codex"}}}` only changes the reviewer assignment.
- `default_runtime` — string override, used as the fallback when a role has no explicit runtime in the merged dict.

The runtime presets / `runtimes` registry itself is **not** per-task overridable in this iteration — adding a new runtime is still a global operation; per-task config only chooses among already-registered runtimes. This keeps the surface narrow and avoids per-task secret drift.

`agentloop/tasks.py` exposes `effective_config(root, task_id)` and `apply_task_config_patch(root, task_id, patch)` for the CLI. `run_one_iteration` switches from `load_config(root)` to `effective_config(root, task_id)` — this is the single hook that makes per-task overrides take effect on the next run (AC-8).

Validation rules in `apply_task_config_patch`:

- `roles[*].runtime` must exist in the merged `runtimes` map (i.e. the global registry).
- `max_iterations` must be a positive int and ≥ current `state.iteration`.
- `test_commands` must be a list of strings.
- Unknown top-level keys raise `WorkspaceError`, so typos surface immediately.

## 6. CLI surface

### 6.1 Lifecycle (single-task)

All of the following accept an optional positional `<task_id>` **and** `--task-id <id>` (the positional wins if both are given). When omitted, `resolve_task_id` is used.

- `agentloop start <task>` — unchanged signature, but no longer rejected when other tasks are active.
- `agentloop approve [<task_id>] [--by NAME]`
- `agentloop cancel [<task_id>] [--by NAME]`
- `agentloop run [<task_id>] [--wait] [--max-iterations N]`
- `agentloop status [<task_id>]`

The ambiguity error (AC-4) prints the list of active task ids with their status, then exits with code 2:

```
error: multiple active tasks; pass --task-id <id>. Candidates:
  - 20260518-093703-agentloop  DESIGNING (it 1/7)
  - 20260518-101200-bugfix     WAITING_FOR_ALIGNMENT
```

### 6.2 Tasks subgroup (inventory + batch)

- `agentloop tasks list [--status STATUS] [--json]` — extended with optional filter and JSON output (used by batch composition and tests).
- `agentloop tasks delete <task_id>` — unchanged.
- `agentloop tasks delete-all` / `clear` — unchanged.
- `agentloop tasks unlock <task_id>` — NEW; removes a stale lock after sanity checks.
- `agentloop tasks migrate` — NEW idempotent command for AC-12; lazily called by every other command as well.

### 6.3 Batch lifecycle

Each batch command takes a **selector group**: `--task-id ID` (repeatable), `--all`, or `--status STATUS` (repeatable). Exactly one mode must be used. A `--dry-run` flag prints the selection without acting.

- `agentloop tasks approve <selector> [--by NAME]`
- `agentloop tasks cancel <selector> [--by NAME]`
- `agentloop tasks run <selector> [--parallel N] [--wait]`

Execution loop for batch lifecycle:

```python
results = []
for tid in selected:
    try:
        with task_lock(root, tid, blocking=args.wait):
            results.append(("ok", tid, op(root, tid)))
    except (WorkspaceError, LockHeld) as exc:
        results.append(("error", tid, str(exc)))
print_batch_summary(results)
return 0 if all_ok else 1
```

Per-task exceptions never abort the rest of the batch (AC-9). The summary lists each id with `ok` / `error` and the error message. Exit code is 0 only if every task succeeded.

`--parallel N` for `tasks run` uses a `ThreadPoolExecutor(max_workers=N)`; because every task has its own lock, files, and runs directory, threads do not contend. Default is `--parallel 1` (sequential) to preserve current behavior and stdout legibility.

### 6.4 Per-task config

- `agentloop tasks config show <task_id> [--effective]` — prints either the raw override file or the merged config.
- `agentloop tasks config set <selector> <key> <value> [--json]`
- `agentloop tasks config unset <selector> <key>`
- `agentloop tasks config clear <selector>` — removes the per-task override file entirely.

`<key>` uses dotted paths: `test_commands`, `max_iterations`, `roles.reviewer.runtime`, `default_runtime`. `--json` treats `<value>` as JSON (needed for lists like `test_commands`). Selector grammar is the same as §6.3, so a single `config set --all` invocation satisfies AC-10. Each task is locked during the patch.

### 6.5 Backward compatibility

- Existing `agentloop status`, `agentloop approve`, `agentloop run`, `agentloop cancel` keep working with no arguments when there is exactly one active task — the resolver handles it transparently (AC-4).
- The legacy global `state.json` is kept on disk (as a pointer) so any external tooling that just reads `task_id` still finds the current one.

## 7. Concurrency-safe runs/

`runner.run_test_commands(root, commands, iteration)` becomes `run_test_commands(root, task_id, commands, iteration)` and writes to `.agentloop/runs/<task_id>/<iteration>/tests/NN-test.log` (AC-5). The single caller in `workflow.run_one_iteration` is updated.

Adapter stdout/stderr logs (already namespaced under `.agentloop/runs/<iteration>/<role>.*.log`) are likewise moved to `.agentloop/runs/<task_id>/<iteration>/<role>.*.log`. The `agents[*].stdout_log` / `stderr_log` paths recorded in state are updated to match — this is a state-format change, captured in §8.

## 8. Migration (AC-12)

A single function `tasks.migrate_workspace(root)` is invoked from `main()` before dispatch (cheap, idempotent). It performs:

1. If `.agentloop/state.json` has a `task_id` but no `.agentloop/tasks/<id>/state.json`, copy it there.
2. If the per-task file exists and the global file still has a `task_id` plus other fields, demote the global file to the pointer form `{schema_version: 2, current_task_id: <id>}`.
3. If `.agentloop/runs/<NNN>/` directories exist at the legacy path (no `task_id` segment), and a current task is detected, move them under `.agentloop/runs/<current_task_id>/`; otherwise leave them in place and warn once.
4. Ensure `.agentloop/locks/` exists.

The migration writes a one-line `.agentloop/MIGRATED` marker so subsequent invocations skip the disk walk after step 1. An explicit `agentloop tasks migrate` simply forces a re-run.

## 9. Module / file ownership

- `agentloop/workspace.py` — keep low-level JSON IO; remove single-task assumptions from `save_state`.
- `agentloop/tasks.py` — NEW; per-task discovery, IO, config merge, resolver, migration.
- `agentloop/locks.py` — NEW; cross-platform per-task file lock context manager.
- `agentloop/workflow.py` — every lifecycle function takes `task_id`; uses `tasks.effective_config`.
- `agentloop/runner.py` — accepts `task_id`; writes namespaced paths.
- `agentloop/cli.py` — adds the resolver wiring, the `tasks config` / `tasks approve|cancel|run|unlock|migrate` subcommands, and the selector parsing helper.
- `agentloop/config.py` — unchanged behavior for the global registry; gains a small helper for validating role→runtime references that `tasks.apply_task_config_patch` reuses.
- `docs/agentloop-design.md` — updated with the new lifecycle diagram, precedence table, lock semantics, and CLI reference (AC-11).

## 10. Test plan (mapped to ACs)

New tests live in `tests/test_multitask.py` (and `tests/test_batch.py` if it grows large). All tests use the manual runtime so they are hermetic.

- AC-1: assert `start` writes per-task state and that mutating it directly is visible to `status` for that id.
- AC-2: start two tasks in sequence within the same workspace; assert both appear in `tasks list` with `WAITING_FOR_ALIGNMENT`.
- AC-3: for each of `approve`, `cancel`, `run`, `status`, invoke with explicit `--task-id` on a non-current task and assert only that task changes.
- AC-4: zero / one / many active-task variants of bare commands; assert the ambiguity error message lists candidate ids.
- AC-5: spawn two `run` subprocesses (via `subprocess.Popen`) targeting different task ids; assert both `state.json` files reach `DONE`, and `runs/<id_a>/.../tests` and `runs/<id_b>/.../tests` exist independently.
- AC-6: acquire the per-task lock manually, attempt `run <id>` in non-blocking mode, assert exit code 2 and the `"locked by pid"` message.
- AC-7: write a per-task `config.json` with a `test_commands` override and assert the next `run` executes only the override command, while another task continues to use the global commands.
- AC-8: `tasks config set <id> test_commands '["echo per-task"]' --json` then `run <id>` and assert the log captures `echo per-task`.
- AC-9: batch `tasks cancel --all` with one task pre-mutated to an invalid state; assert the summary reports `error` for that id and `ok` for the rest, and the other tasks are actually cancelled.
- AC-10: `tasks config set --all max_iterations 3` and assert every per-task `config.json` contains the override.
- AC-12: prepare a workspace with only the legacy `state.json` populated; invoke any command and assert `tasks/<id>/state.json` now exists, the global file is demoted, and the prior task is fully usable.

## 11. Rollout / open questions resolved

- Q1 (default active task): keep backwards-compatible single-task fallback via `resolve_task_id`; do not force `--task-id`.
- Q2 (concurrency model): users may launch parallel processes themselves; `tasks run --parallel N` is provided as a convenience but is not required for safety — the lock model carries the guarantee.
- Q3 (override surface): `test_commands`, `max_iterations`, `roles.*.runtime`, `default_runtime`. Runtime registry is global only.
- Q4 (batch filter): `--task-id` / `--all` / `--status` for now; tags/labels deferred.
- Q5 (migration): lazy on every invocation, plus explicit `tasks migrate`.
- Q6 (lock semantics): default non-blocking with descriptive error; stale-pid auto-reclaim with warning; `tasks unlock` for manual override.
- Q7 (scope): one shot — the criteria require lifecycle + per-task config + batch in a single iteration, which the module split above keeps tractable.
