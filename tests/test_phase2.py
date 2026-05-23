from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agentloop.cli import main


class PhaseTwoCliTests(unittest.TestCase):
    def test_start_creates_analysis_acceptance_and_waits_for_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "init"]), 0)

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "start", "Build a reusable agent loop"])

            self.assertEqual(exit_code, 0)
            self.assertIn("WAITING_FOR_ALIGNMENT", output.getvalue())

            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "WAITING_FOR_ALIGNMENT")
            self.assertEqual(state["current_phase"], "alignment")
            self.assertTrue(state["requires_human_approval"])
            self.assertEqual(state["goal"]["raw_request"], "Build a reusable agent loop")
            self.assertGreaterEqual(len(state["acceptance_criteria"]), 2)
            self.assertEqual([item["role"] for item in state["agents"]], ["analyst"])
            self.assertEqual(state["phases"]["analysis"]["status"], "completed")
            self.assertEqual(state["phases"]["alignment"]["status"], "waiting_for_approval")

            analysis_ref = state["phases"]["analysis"]["artifact"]
            acceptance_ref = state["phases"]["alignment"]["artifact"]
            self.assertTrue(analysis_ref.startswith(".agentloop/tasks/"))
            self.assertTrue(acceptance_ref.startswith(".agentloop/tasks/"))
            analysis = (root / analysis_ref).read_text(encoding="utf-8")
            acceptance = (root / acceptance_ref).read_text(encoding="utf-8")
            acceptance_json = (root / acceptance_ref.replace("acceptance.md", "acceptance.json"))
            self.assertIn("Build a reusable agent loop", analysis)
            self.assertTrue(acceptance_json.exists())
            self.assertIn("AC-1", acceptance)
            self.assertIn("Build a reusable agent loop", acceptance)
            self.assertNotIn("The workflow remains independent of any specific coding agent runtime", acceptance)

    def test_approve_moves_task_to_ready_to_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                main(["--root", str(root), "start", "Build a reusable agent loop"])

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "approve", "--by", "chen"])

            self.assertEqual(exit_code, 0)
            self.assertIn("READY_TO_START", output.getvalue())

            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "READY_TO_START")
            self.assertEqual(state["current_phase"], "start")
            self.assertFalse(state["requires_human_approval"])
            self.assertEqual(state["phases"]["alignment"]["status"], "approved")
            self.assertEqual(state["phases"]["alignment"]["approved_by"], "chen")
            self.assertTrue(all(item["status"] == "pending" for item in state["acceptance_criteria"]))

    def test_start_uses_analyst_runtime_for_task_specific_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])

            script = root / "analyst_agent.py"
            script.write_text(
                "from pathlib import Path\n"
                "import json\n"
                "task_dirs = sorted((Path('.agentloop') / 'tasks').iterdir())\n"
                "artifact_dir = task_dirs[-1] / 'artifacts'\n"
                "artifact_dir.mkdir(parents=True, exist_ok=True)\n"
                "(artifact_dir / 'analysis.md').write_text('# Custom Analysis\\nRuntime analyzed doctor command.', encoding='utf-8')\n"
                "criteria = {'acceptance_criteria': [{'id': 'AC-CUSTOM', 'description': 'doctor reports PASS and FAIL checks', 'verification': 'unit_test', 'required': True, 'status': 'pending', 'evidence': 'tests'}]}\n"
                "(artifact_dir / 'acceptance.json').write_text(json.dumps(criteria), encoding='utf-8')\n"
                "(artifact_dir / 'acceptance.md').write_text('# Custom Acceptance\\nAC-CUSTOM doctor reports PASS and FAIL checks', encoding='utf-8')\n",
                encoding="utf-8",
            )
            config_path = root / ".agentloop" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["runtimes"]["fake-analyst"] = {"adapter": "command", "command": sys.executable, "args": [str(script)]}
            config["roles"]["analyst"] = {"runtime": "fake-analyst"}
            config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                exit_code = main(["--root", str(root), "start", "Add doctor command"])

            self.assertEqual(exit_code, 0)
            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["agents"][0]["role"], "analyst")
            self.assertEqual(state["agents"][0]["adapter"], "command")
            self.assertEqual(state["acceptance_criteria"][0]["id"], "AC-CUSTOM")
            self.assertEqual(state["acceptance_criteria"][0]["description"], "doctor reports PASS and FAIL checks")

    def test_start_marks_performance_regression_as_automated_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                exit_code = main(
                    [
                        "--root",
                        str(root),
                        "start",
                        "Fix the performance regression in tests/test_loop/duplicate_transactions.py. The function produces correct results but is too slow on large inputs.",
                    ]
                )

            self.assertEqual(exit_code, 0)
            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            verifications = {item["verification"] for item in state["acceptance_criteria"]}
            self.assertIn("automated_test", verifications)

            analyst_prompt = (root / ".agentloop" / "prompts" / "analyst.md").read_text(encoding="utf-8")
            self.assertIn("Verification Plan", analyst_prompt)
            self.assertIn("regression test file or command", analyst_prompt)

    def test_approve_requires_waiting_for_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(["--root", str(root), "approve"])

            self.assertEqual(exit_code, 2)
            self.assertIn("Cannot approve while status is CREATED", stderr.getvalue())

    def test_cancel_active_task_allows_new_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                main(["--root", str(root), "start", "Task to cancel"])

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "cancel", "--by", "chen"])

            self.assertEqual(exit_code, 0)
            self.assertIn("CANCELLED", output.getvalue())
            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "CANCELLED")
            self.assertEqual(state["current_phase"], "cancelled")
            self.assertEqual(state["cancelled_by"], "chen")

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "start", "Replacement task"]), 0)

            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["title"], "Replacement task")
            self.assertEqual(state["status"], "WAITING_FOR_ALIGNMENT")

    def test_cancel_requires_active_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(["--root", str(root), "cancel"])

            self.assertEqual(exit_code, 2)
            self.assertIn("Cannot cancel while status is CREATED", stderr.getvalue())

    def test_tasks_lists_current_and_older_task_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                main(["--root", str(root), "start", "Listed task"])

            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            legacy_dir = root / ".agentloop" / "tasks" / "legacy-task-without-state"
            (legacy_dir / "artifacts").mkdir(parents=True)

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "tasks"])

            text = output.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("AgentLoop tasks", text)
            self.assertIn(f"* {state['task_id']}", text)
            self.assertIn("status: WAITING_FOR_ALIGNMENT", text)
            self.assertIn("title: Listed task", text)
            self.assertIn("legacy-task-without-state", text)
            self.assertIn("status: UNKNOWN", text)

    def test_tasks_delete_non_current_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                main(["--root", str(root), "start", "First task"])
                main(["--root", str(root), "cancel"])
                main(["--root", str(root), "start", "Second task"])

            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            current_task_id = state["task_id"]
            old_task_id = next(path.name for path in (root / ".agentloop" / "tasks").iterdir() if path.name != current_task_id)

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "tasks", "delete", old_task_id])

            self.assertEqual(exit_code, 0)
            self.assertIn("AgentLoop task deleted", output.getvalue())
            self.assertFalse((root / ".agentloop" / "tasks" / old_task_id).exists())
            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["task_id"], current_task_id)
            self.assertEqual(state["status"], "WAITING_FOR_ALIGNMENT")

    def test_tasks_delete_current_task_resets_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                main(["--root", str(root), "start", "Current task"])

            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            task_id = state["task_id"]
            with redirect_stdout(io.StringIO()):
                exit_code = main(["--root", str(root), "tasks", "delete", task_id])

            self.assertEqual(exit_code, 0)
            self.assertFalse((root / ".agentloop" / "tasks" / task_id).exists())
            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "CREATED")
            self.assertIsNone(state["task_id"])

    def test_tasks_delete_all_resets_state_and_removes_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                main(["--root", str(root), "start", "First task"])
                main(["--root", str(root), "cancel"])
                main(["--root", str(root), "start", "Second task"])

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "tasks", "delete-all"])

            self.assertEqual(exit_code, 0)
            self.assertIn("deleted: 2", output.getvalue())
            self.assertEqual(list((root / ".agentloop" / "tasks").iterdir()), [])
            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "CREATED")
            self.assertIsNone(state["task_id"])

    def test_start_after_done_resets_execution_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                main(["--root", str(root), "start", "First task"])
                main(["--root", str(root), "approve"])
                main(["--root", str(root), "run"])
                main(["--root", str(root), "start", "Second task"])

            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["title"], "Second task")
            self.assertEqual(state["status"], "WAITING_FOR_ALIGNMENT")
            self.assertEqual([item["role"] for item in state["agents"]], ["analyst"])
            self.assertEqual(state["phases"]["design"]["status"], "pending")
            self.assertEqual(state["phases"]["review"]["last_review"], None)
            self.assertTrue(state["phases"]["analysis"]["artifact"].startswith(".agentloop/tasks/"))


if __name__ == "__main__":
    unittest.main()
