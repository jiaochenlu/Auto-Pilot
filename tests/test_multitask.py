from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agentloop.cli import main
from agentloop.locks import task_lock


def silently(args: list[str]) -> int:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return main(args)


def start_task(root: Path, title: str) -> str:
    with redirect_stdout(io.StringIO()):
        main(["--root", str(root), "init"])
    with redirect_stdout(io.StringIO()):
        main(["--root", str(root), "start", title])
    state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
    return state["task_id"]


def start_extra(root: Path, title: str) -> str:
    with redirect_stdout(io.StringIO()):
        main(["--root", str(root), "start", title])
    state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
    return state["task_id"]


def task_state(root: Path, task_id: str) -> dict:
    return json.loads((root / ".agentloop" / "tasks" / task_id / "state.json").read_text(encoding="utf-8"))


class MultiTaskLifecycleTests(unittest.TestCase):
    def test_start_allows_multiple_concurrent_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tid_a = start_task(root, "first task")
            tid_b = start_extra(root, "second task")
            self.assertNotEqual(tid_a, tid_b)
            self.assertEqual(task_state(root, tid_a)["status"], "WAITING_FOR_ALIGNMENT")
            self.assertEqual(task_state(root, tid_b)["status"], "WAITING_FOR_ALIGNMENT")

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "tasks", "list"])
            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn(tid_a, text)
            self.assertIn(tid_b, text)

    def test_explicit_task_id_targets_non_current_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tid_a = start_task(root, "alpha task")
            tid_b = start_extra(root, "beta task")  # tid_b becomes current

            # Approve the non-current task explicitly.
            with redirect_stdout(io.StringIO()):
                exit_code = main(["--root", str(root), "approve", "--task-id", tid_a])
            self.assertEqual(exit_code, 0)
            self.assertEqual(task_state(root, tid_a)["status"], "READY_TO_START")
            self.assertEqual(task_state(root, tid_b)["status"], "WAITING_FOR_ALIGNMENT")

            # Cancel the non-current task explicitly.
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "cancel", tid_a])
            self.assertEqual(task_state(root, tid_a)["status"], "CANCELLED")
            self.assertEqual(task_state(root, tid_b)["status"], "WAITING_FOR_ALIGNMENT")

    def test_ambiguous_bare_command_lists_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tid_a = start_task(root, "alpha")
            tid_b = start_extra(root, "beta")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(["--root", str(root), "approve"])
            self.assertEqual(exit_code, 2)
            text = stderr.getvalue()
            self.assertIn("multiple active tasks", text)
            self.assertIn(tid_a, text)
            self.assertIn(tid_b, text)

    def test_bare_command_works_with_single_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tid = start_task(root, "only one")
            with redirect_stdout(io.StringIO()):
                code = main(["--root", str(root), "approve"])
            self.assertEqual(code, 0)
            self.assertEqual(task_state(root, tid)["status"], "READY_TO_START")


class PerTaskConfigTests(unittest.TestCase):
    def test_per_task_test_commands_override_takes_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tid = start_task(root, "config override task")
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "approve"])

            # Set per-task test_commands via CLI.
            with redirect_stdout(io.StringIO()):
                code = main([
                    "--root", str(root), "tasks", "config", "set",
                    "--task-id", tid, "test_commands",
                    '["python -c \\"print(\'per-task-marker\')\\""]',
                    "--json",
                ])
            self.assertEqual(code, 0)

            override = json.loads((root / ".agentloop" / "tasks" / tid / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(override["test_commands"], ["python -c \"print('per-task-marker')\""])

            with redirect_stdout(io.StringIO()):
                code = main(["--root", str(root), "run", "--task-id", tid])
            self.assertEqual(code, 0)
            log = (root / ".agentloop" / "runs" / tid / "001" / "tests" / "01-test.log").read_text(encoding="utf-8")
            self.assertIn("per-task-marker", log)

    def test_config_show_returns_override_and_effective(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tid = start_task(root, "show task")
            with redirect_stdout(io.StringIO()):
                main([
                    "--root", str(root), "tasks", "config", "set",
                    "--task-id", tid, "max_iterations", "3",
                ])
            output = io.StringIO()
            with redirect_stdout(output):
                main(["--root", str(root), "tasks", "config", "show", tid])
            data = json.loads(output.getvalue())
            self.assertEqual(data, {"max_iterations": 3})

            output = io.StringIO()
            with redirect_stdout(output):
                main(["--root", str(root), "tasks", "config", "show", tid, "--effective"])
            merged = json.loads(output.getvalue())
            self.assertEqual(merged["max_iterations"], 3)
            self.assertIn("runtimes", merged)


class BatchOperationsTests(unittest.TestCase):
    def test_batch_config_set_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tid_a = start_task(root, "alpha")
            tid_b = start_extra(root, "beta")
            with redirect_stdout(io.StringIO()):
                code = main([
                    "--root", str(root), "tasks", "config", "set",
                    "--all", "max_iterations", "5",
                ])
            self.assertEqual(code, 0)
            for tid in (tid_a, tid_b):
                override = json.loads((root / ".agentloop" / "tasks" / tid / "config.json").read_text(encoding="utf-8"))
                self.assertEqual(override["max_iterations"], 5)

    def test_batch_cancel_isolates_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tid_a = start_task(root, "alpha")
            tid_b = start_extra(root, "beta")
            # Force tid_a into an uncancellable terminal state.
            state = task_state(root, tid_a)
            state["status"] = "DONE"
            (root / ".agentloop" / "tasks" / tid_a / "state.json").write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "tasks", "cancel", "--all"])
            text = output.getvalue()
            self.assertEqual(code, 1)
            self.assertIn(tid_a, text)
            self.assertIn(tid_b, text)
            self.assertIn("error", text)
            # tid_b should now be cancelled.
            self.assertEqual(task_state(root, tid_b)["status"], "CANCELLED")
            # tid_a stays DONE because of the simulated terminal state.
            self.assertEqual(task_state(root, tid_a)["status"], "DONE")

    def test_run_namespaces_logs_per_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tid_a = start_task(root, "alpha")
            tid_b = start_extra(root, "beta")
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "approve", "--task-id", tid_a])
                main(["--root", str(root), "approve", "--task-id", tid_b])
                main(["--root", str(root), "tasks", "run", "--task-id", tid_a, "--task-id", tid_b])
            for tid in (tid_a, tid_b):
                run_dir = root / ".agentloop" / "runs" / tid / "001"
                self.assertTrue(run_dir.is_dir(), f"missing run dir for {tid}")
                self.assertTrue((run_dir / "architect.stdout.log").exists())


class LockingTests(unittest.TestCase):
    def test_run_fails_fast_when_task_locked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tid = start_task(root, "locked task")
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "approve"])

            with task_lock(root, tid, blocking=False):
                stderr = io.StringIO()
                with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                    code = main(["--root", str(root), "run", tid])
            self.assertEqual(code, 2)
            self.assertIn("locked by pid", stderr.getvalue())

    def test_unlock_removes_stale_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tid = start_task(root, "stale task")
            from agentloop.locks import lock_path
            lp = lock_path(root, tid)
            lp.write_text(json.dumps({"pid": 999999999, "started_at": "x", "host": "x"}), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                code = main(["--root", str(root), "tasks", "unlock", tid])
            self.assertEqual(code, 0)
            self.assertFalse(lp.exists())


class MigrationTests(unittest.TestCase):
    def test_migration_copies_legacy_state_into_per_task_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                main(["--root", str(root), "start", "legacy"])
            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            tid = state["task_id"]
            # Simulate pre-migration repo by deleting the per-task copy.
            per_task = root / ".agentloop" / "tasks" / tid / "state.json"
            per_task.unlink()
            self.assertFalse(per_task.exists())

            with redirect_stdout(io.StringIO()):
                code = main(["--root", str(root), "tasks", "migrate"])
            self.assertEqual(code, 0)
            self.assertTrue(per_task.exists())
            restored = json.loads(per_task.read_text(encoding="utf-8"))
            self.assertEqual(restored["task_id"], tid)


if __name__ == "__main__":
    unittest.main()
