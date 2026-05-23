from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from agentloop.cli import main


def read_json(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def init_approved_task(root: Path) -> None:
    with redirect_stdout(io.StringIO()):
        main(["--root", str(root), "init"])
        main(["--root", str(root), "start", "Build AgentLoop"])
        main(["--root", str(root), "approve"])


class PhaseThreeCliTests(unittest.TestCase):
    def test_run_manual_runtime_completes_when_no_tests_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_approved_task(root)

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "run"])

            self.assertEqual(exit_code, 0)
            self.assertIn("status: DONE", output.getvalue())

            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "DONE")
            self.assertEqual(state["iteration"], 1)
            self.assertEqual(state["phases"]["design"]["status"], "completed")
            self.assertEqual(state["phases"]["test_authoring"]["status"], "completed")
            self.assertEqual(state["phases"]["testing"]["status"], "completed")
            self.assertEqual(state["phases"]["review"]["status"], "approved")
            roles = [item["role"] for item in state["agents"]]
            self.assertEqual(roles, ["analyst", "architect", "tester", "implementer", "tester", "reviewer", "integrator"])
            self.assertTrue(all(item["adapter"] == "manual" for item in state["agents"]))
            self.assertTrue(all("\\" not in item["stdout_log"] for item in state["agents"]))

            design_ref = state["phases"]["design"]["artifact"]
            test_plan_ref = state["phases"]["testing"]["artifact"]
            review_ref = state["phases"]["review"]["last_review"]
            final_ref = f".agentloop/tasks/{state['task_id']}/artifacts/final-report.md"
            self.assertTrue((root / design_ref).exists())
            self.assertTrue((root / test_plan_ref).exists())
            self.assertTrue((root / review_ref).exists())
            self.assertTrue((root / final_ref).exists())
            final_report = (root / final_ref).read_text(encoding="utf-8")
            self.assertIn(f"`{review_ref}`", final_report)
            self.assertNotIn(".agentloop/artifacts/.agentloop/artifacts", final_report)

            review = read_json(root, review_ref)
            self.assertEqual(review["decision"], "APPROVED")

            tester_prompt = (root / ".agentloop" / "prompts" / "tester.md").read_text(encoding="utf-8")
            self.assertIn("After implementation", tester_prompt)

    def test_run_prompts_tester_to_author_tests_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_approved_task(root)

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "run"])

            self.assertEqual(exit_code, 0)
            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            roles = [item["role"] for item in state["agents"]]
            self.assertLess(roles.index("tester"), roles.index("implementer"))
            self.assertEqual(state["phases"]["test_authoring"]["status"], "completed")

    def test_run_records_failed_test_and_requests_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_approved_task(root)

            config_path = root / ".agentloop" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["test_commands"] = ["python -c \"import sys; sys.exit(3)\""]
            config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                exit_code = main(["--root", str(root), "run"])

            self.assertEqual(exit_code, 0)
            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "BLOCKED")
            self.assertEqual(state["current_phase"], "blocked")
            self.assertEqual(state["iteration"], 7)
            self.assertEqual(state["phases"]["review"]["status"], "changes_required")

            review = read_json(root, f".agentloop/tasks/{state['task_id']}/artifacts/review-001.json")
            self.assertEqual(review["decision"], "CHANGES_REQUIRED")
            self.assertEqual(review["test_results"][0]["exit_code"], 3)
            self.assertTrue((root / f".agentloop/tasks/{state['task_id']}/artifacts/review-007.json").exists())

    def test_run_auto_iterates_until_tests_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_approved_task(root)

            script = root / "flaky_test.py"
            script.write_text(
                "from pathlib import Path\n"
                "marker = Path('.agentloop/flaky-marker')\n"
                "if not marker.exists():\n"
                "    marker.write_text('failed-once', encoding='utf-8')\n"
                "    raise SystemExit(4)\n"
                "raise SystemExit(0)\n",
                encoding="utf-8",
            )
            config_path = root / ".agentloop" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["test_commands"] = [f"python {script}"]
            config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                exit_code = main(["--root", str(root), "run"])

            self.assertEqual(exit_code, 0)
            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "DONE")
            self.assertEqual(state["iteration"], 2)
            first_review_ref = f".agentloop/tasks/{state['task_id']}/artifacts/review-001.json"
            second_review_ref = f".agentloop/tasks/{state['task_id']}/artifacts/review-002.json"
            self.assertTrue((root / first_review_ref).exists())
            self.assertTrue((root / second_review_ref).exists())

            first_review = read_json(root, first_review_ref)
            second_review = read_json(root, second_review_ref)
            self.assertEqual(first_review["decision"], "CHANGES_REQUIRED")
            self.assertEqual(second_review["decision"], "APPROVED")


if __name__ == "__main__":
    unittest.main()
