from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentloop.api import (
    approve_task_api,
    build_settings,
    build_task_detail,
    build_task_list,
    create_task,
    delete_task,
    patch_task_config,
    resume_task_api,
    start_research_api,
    submit_framing_answers_api,
)
from agentloop.tasks import load_task_state, save_task_state, set_current_task_id
from agentloop.ui import AgentLoopUIHandler
from agentloop.workspace import init_workspace
from agentloop.workflow import approve_task, start_task


def _answer_blocking_and_start_research(root: Path, task_id: str, initial_state: dict) -> dict:
    """Helper: answer all blocking framing questions then run start_research."""
    answers = {q["id"]: f"answer for {q['id']}" for q in initial_state.get("framing_questions", []) if q.get("blocking")}
    submit_framing_answers_api(root, task_id, {"by": "ui", "answers": answers})
    return start_research_api(root, task_id, {"by": "ui"})


class UIApiTests(unittest.TestCase):
    def test_task_list_marks_current_and_handles_malformed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            good = start_task(root, "build the console")
            good_id = good["task_id"]
            bad_dir = root / ".agentloop" / "tasks" / "bad-task"
            bad_dir.mkdir(parents=True)
            (bad_dir / "state.json").write_text("{not json", encoding="utf-8")
            set_current_task_id(root, good_id)

            data = build_task_list(root)
            rows = {row["task_id"]: row for row in data["tasks"]}
            self.assertTrue(rows[good_id]["current"])
            self.assertEqual(rows[good_id]["status"], "FRAMING_REVIEW")
            self.assertEqual(rows["bad-task"]["status"], "UNKNOWN")
            self.assertIn("Invalid task state", rows["bad-task"]["error"])

    def test_create_task_uses_workflow_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            detail = create_task(root, {"request": "ship a UI"})
            task_id = detail["state"]["task_id"]
            self.assertEqual(detail["state"]["status"], "FRAMING_REVIEW")
            self.assertTrue(detail["framing_review"]["required"])
            artifact_dir = root / ".agentloop" / "tasks" / task_id / "artifacts"
            self.assertTrue((artifact_dir / "framing.md").exists())
            self.assertTrue((artifact_dir / "framing.json").exists())

            answers = {q["id"]: f"answer {q['id']}" for q in detail["framing_review"]["questions"] if q.get("blocking")}
            reviewed = submit_framing_answers_api(root, task_id, {"by": "ui", "answers": answers})
            self.assertEqual(reviewed["state"]["status"], "FRAMING_REVIEW")
            self.assertTrue(reviewed["framing_review"].get("ready_for_research"))
            self.assertTrue(reviewed["actions"]["start_research"]["enabled"])

            researched = start_research_api(root, task_id, {"by": "ui"})
            self.assertEqual(researched["state"]["status"], "WAITING_FOR_ALIGNMENT")
            self.assertTrue(researched["execution_approval"]["required"])
            self.assertTrue((artifact_dir / "research.md").exists())
            self.assertTrue((artifact_dir / "proposal.md").exists())
            self.assertTrue((artifact_dir / "acceptance.md").exists())
            self.assertTrue((artifact_dir / "acceptance.json").exists())
            self.assertTrue((artifact_dir / "test-plan.md").exists())

    def test_create_task_accepts_role_runtime_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            detail = create_task(
                root,
                {
                    "request": "ship a UI",
                    "role_runtimes": {"framer": "manual", "architect": "manual", "tester": "manual"},
                },
            )
            task_id = detail["state"]["task_id"]
            config = json.loads((root / ".agentloop" / "tasks" / task_id / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["roles"]["framer"]["runtime"], "manual")
            self.assertEqual(config["roles"]["architect"]["runtime"], "manual")
            self.assertEqual(config["roles"]["tester"]["runtime"], "manual")

    def test_create_task_does_not_run_selected_investigator_before_research(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            config_path = root / ".agentloop" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["runtimes"]["fail-fast"] = {
                "adapter": "command",
                "command": "python",
                "args": ["-c", "import sys; sys.exit(17)"],
                "stdin_file": "{prompt_file}",
            }
            config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

            detail = create_task(root, {"request": "ship a UI", "role_runtimes": {"investigator": "fail-fast"}})

            self.assertEqual(detail["state"]["status"], "FRAMING_REVIEW")
            task_id = detail["state"]["task_id"]
            agents = load_task_state(root, task_id)["agents"]
            agent_roles = [a["role"] for a in agents]
            self.assertNotIn("investigator", agent_roles)
            self.assertNotIn("architect", agent_roles)
            artifact_dir = root / ".agentloop" / "tasks" / task_id / "artifacts"
            self.assertTrue((artifact_dir / "framing.md").exists())
            self.assertTrue((artifact_dir / "framing.json").exists())
            self.assertFalse((artifact_dir / "research.md").exists())

    def test_settings_include_usage_runtimes_and_role_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            create_task(root, {"request": "ship a UI"})

            settings = build_settings(root)
            self.assertEqual(settings["usage"]["task_count"], 1)
            runtimes = {item["name"]: item for item in settings["runtime"]["runtimes"]}
            runtime_names = set(runtimes)
            self.assertIn("manual", runtime_names)
            self.assertNotIn("example-agent", runtime_names)
            self.assertEqual(runtimes["manual"]["status"], "manual_fallback")
            self.assertTrue(runtimes["manual"]["selectable"])
            self.assertIn("codex", runtime_names)
            self.assertIn(runtimes["codex"]["status"], {"active", "configured_missing", "detected_not_injected", "not_injected"})
            role_defaults = {item["role"]: item["runtime"] for item in settings["runtime"]["role_defaults"]}
            self.assertEqual(role_defaults["framer"], "manual")
            self.assertEqual(role_defaults["architect"], "manual")
            self.assertEqual(role_defaults["tester"], "manual")

    def test_detail_includes_artifacts_runtime_and_test_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            state = start_task(root, "show logs")
            task_id = state["task_id"]
            stdout = root / ".agentloop" / "runs" / task_id / "001" / "tester.stdout.log"
            stderr = root / ".agentloop" / "runs" / task_id / "001" / "tester.stderr.log"
            stdout.parent.mkdir(parents=True)
            stdout.write_text("hello stdout", encoding="utf-8")
            stderr.write_text("", encoding="utf-8")
            tests_dir = stdout.parent / "tests"
            tests_dir.mkdir()
            (tests_dir / "01-test.log").write_text("COMMAND\npython -m unittest\n", encoding="utf-8")
            state = load_task_state(root, task_id)
            state["iteration"] = 1
            state["agents"].append(
                {
                    "role": "tester",
                    "runtime": "manual",
                    "exit_code": 0,
                    "stdout_log": stdout.relative_to(root).as_posix(),
                    "stderr_log": stderr.relative_to(root).as_posix(),
                    "artifacts": [],
                }
            )
            save_task_state(root, task_id, state)

            detail = build_task_detail(root, task_id)
            self.assertTrue(detail["artifacts"])
            self.assertEqual(detail["runtime"]["latest_iteration"], 1)
            self.assertIn("hello stdout", detail["runtime"]["agents"][0]["stdout"]["content"])
            test_entry = detail["runtime"]["tests"][0]
            self.assertEqual(test_entry["command"], "python -m unittest")
            self.assertIsNone(test_entry["exit_code"])
            self.assertIsNone(test_entry["duration_ms"])
            self.assertIn("python -m unittest", test_entry["log"]["content"])

    def test_detail_merges_structured_test_result_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            state = start_task(root, "show structured test output")
            task_id = state["task_id"]
            tests_dir = root / ".agentloop" / "runs" / task_id / "001" / "tests"
            tests_dir.mkdir(parents=True)
            (tests_dir / "01-test.log").write_text(
                "COMMAND\npython -m unittest discover -s tests\n\nSTDOUT\nok\n",
                encoding="utf-8",
            )
            artifacts_dir = root / ".agentloop" / "tasks" / task_id / "artifacts"
            (artifacts_dir / "review-001.json").write_text(
                json.dumps(
                    {
                        "decision": "APPROVED",
                        "test_results": [
                            {
                                "command": "python -m unittest discover -s tests",
                                "exit_code": 0,
                                "duration_ms": 24172,
                                "log": f".agentloop/runs/{task_id}/001/tests/01-test.log",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state = load_task_state(root, task_id)
            state["iteration"] = 1
            save_task_state(root, task_id, state)

            detail = build_task_detail(root, task_id)
            test_entry = detail["runtime"]["tests"][0]
            self.assertEqual(test_entry["name"], "01-test.log")
            self.assertEqual(test_entry["command"], "python -m unittest discover -s tests")
            self.assertEqual(test_entry["exit_code"], 0)
            self.assertEqual(test_entry["duration_ms"], 24172)
            self.assertIn("STDOUT", test_entry["log"]["content"])

    def test_detail_includes_structured_test_result_with_missing_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            state = start_task(root, "show missing structured test log")
            task_id = state["task_id"]
            artifacts_dir = root / ".agentloop" / "tasks" / task_id / "artifacts"
            (artifacts_dir / "review-001.json").write_text(
                json.dumps(
                    {
                        "decision": "CHANGES_REQUIRED",
                        "test_results": [
                            {
                                "command": "python -m pytest tests/test_ui_api.py -v",
                                "exit_code": 1,
                                "duration_ms": 3000,
                                "log": f".agentloop/runs/{task_id}/001/tests/01-test.log",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state = load_task_state(root, task_id)
            state["iteration"] = 1
            save_task_state(root, task_id, state)

            detail = build_task_detail(root, task_id)
            test_entry = detail["runtime"]["tests"][0]
            self.assertEqual(test_entry["command"], "python -m pytest tests/test_ui_api.py -v")
            self.assertEqual(test_entry["exit_code"], 1)
            self.assertEqual(test_entry["duration_ms"], 3000)
            self.assertTrue(test_entry["log"]["missing"])

    def test_patch_config_and_delete_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            state = start_task(root, "config task")
            task_id = state["task_id"]

            detail = patch_task_config(root, task_id, {"max_iterations": 3, "test_commands": ["python -V"]})
            self.assertEqual(detail["config"]["override"]["max_iterations"], 3)
            config = json.loads((root / ".agentloop" / "tasks" / task_id / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["test_commands"], ["python -V"])
            readonly = root / ".agentloop" / "tasks" / task_id / "artifacts" / "readonly.txt"
            readonly.write_text("locked by attributes", encoding="utf-8")
            readonly.chmod(0o400)

            try:
                result = delete_task(root, task_id, {"confirm": task_id})
                self.assertTrue(result["deleted"])
                self.assertFalse((root / ".agentloop" / "tasks" / task_id).exists())
            finally:
                if readonly.exists():
                    readonly.chmod(0o700)

    def test_actions_reflect_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            state = start_task(root, "approval task")
            task_id = state["task_id"]
            framing_detail = build_task_detail(root, task_id)
            self.assertEqual(framing_detail["state"]["status"], "FRAMING_REVIEW")
            self.assertTrue(framing_detail["actions"]["submit_framing"]["enabled"])
            self.assertFalse(framing_detail["actions"]["approve"]["enabled"])
            self.assertFalse(framing_detail["actions"]["run"]["enabled"])

            researched = _answer_blocking_and_start_research(root, task_id, state)
            self.assertEqual(researched["state"]["status"], "WAITING_FOR_ALIGNMENT")
            self.assertTrue(researched["actions"]["approve"]["enabled"])
            self.assertFalse(researched["actions"]["run"]["enabled"])

            approved = approve_task_api(root, task_id, {"by": "ui"})
            self.assertFalse(approved["actions"]["approve"]["enabled"])
            self.assertFalse(approved["actions"]["run"]["enabled"])
            self.assertEqual(approved["state"]["status"], "DONE")

    def test_human_review_detail_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            state = start_task(root, "blocked task")
            task_id = state["task_id"]
            artifacts_dir = root / ".agentloop" / "tasks" / task_id / "artifacts"
            (artifacts_dir / "review-001.json").write_text(
                json.dumps(
                    {
                        "decision": "BLOCKED",
                        "summary": "Need human input for missing credentials.",
                        "comments": [
                            {
                                "severity": "high",
                                "area": "runtime",
                                "text": "The runtime cannot access credentials.",
                                "required_action": "Configure credentials and resume.",
                            }
                        ],
                        "test_results": [{"command": "python -m unittest", "exit_code": 2, "log": "missing.log"}],
                    }
                ),
                encoding="utf-8",
            )
            state = load_task_state(root, task_id)
            state["status"] = "WAITING_FOR_HUMAN"
            state["current_phase"] = "human_review"
            state["requires_human_approval"] = True
            save_task_state(root, task_id, state)

            detail = build_task_detail(root, task_id)
            self.assertTrue(detail["human_review"]["required"])
            self.assertIn("Need human input", detail["human_review"]["review"]["summary"])
            self.assertEqual(detail["human_review"]["review"]["test_results"][0]["exit_code"], 2)

            resumed = resume_task_api(root, task_id, {"by": "ui", "note": "Credentials configured."})
            self.assertEqual(resumed["state"]["status"], "IMPLEMENTING_AND_TESTING")
            resumed_state = load_task_state(root, task_id)
            self.assertEqual(resumed_state["human_reviews"][0]["note"], "Credentials configured.")
            self.assertFalse(resumed_state["requires_human_approval"])

    def test_http_ui_endpoints_back_task_crud_and_static_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)

            class Server(ThreadingHTTPServer):
                pass

            server = Server(("127.0.0.1", 0), AgentLoopUIHandler)
            server.root = root.resolve()  # type: ignore[attr-defined]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            def request(path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict | str, str]:
                body = None if payload is None else json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{base_url}{path}",
                    data=body,
                    method=method,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    raw = response.read().decode("utf-8")
                    content_type = response.headers.get("Content-Type", "")
                    data: dict | str = json.loads(raw) if "application/json" in content_type else raw
                    return response.status, data, content_type

            try:
                status, html, content_type = request("/")
                self.assertEqual(status, 200)
                self.assertIn("text/html", content_type)
                self.assertIn("AgentLoop Task Console", html)
                self.assertIn('id="deleteError"', html)
                self.assertIn('id="deleteSubmitBtn"', html)
                self.assertNotIn('id="deleteConfirmInput"', html)
                self.assertNotIn('method="dialog" id="deleteForm"', html)

                status, detail, _ = request("/api/tasks", "POST", {"request": "manage UI tasks"})
                self.assertEqual(status, 201)
                self.assertIsInstance(detail, dict)
                task_id = detail["state"]["task_id"]
                self.assertEqual(detail["state"]["status"], "FRAMING_REVIEW")
                self.assertTrue(detail["framing_review"]["required"])

                blocking_answers = {
                    q["id"]: f"answer {q['id']}"
                    for q in detail["framing_review"]["questions"]
                    if q.get("blocking")
                }
                status, reviewed, _ = request(
                    f"/api/tasks/{task_id}/submit-framing",
                    "POST",
                    {"by": "ui", "answers": blocking_answers},
                )
                self.assertEqual(status, 200)
                self.assertIsInstance(reviewed, dict)
                self.assertEqual(reviewed["state"]["status"], "FRAMING_REVIEW")
                self.assertTrue(reviewed["framing_review"].get("ready_for_research"))

                status, researched, _ = request(
                    f"/api/tasks/{task_id}/start-research",
                    "POST",
                    {"by": "ui"},
                )
                self.assertEqual(status, 200)
                self.assertIsInstance(researched, dict)
                self.assertEqual(researched["state"]["status"], "WAITING_FOR_ALIGNMENT")

                status, task_list, _ = request("/api/tasks")
                self.assertEqual(status, 200)
                self.assertIsInstance(task_list, dict)
                self.assertEqual(task_list["tasks"][0]["task_id"], task_id)

                status, settings, _ = request("/api/settings")
                self.assertEqual(status, 200)
                self.assertIsInstance(settings, dict)
                self.assertGreaterEqual(settings["usage"]["task_count"], 1)
                self.assertTrue(settings["runtime"]["runtimes"])

                status, patched, _ = request(
                    f"/api/tasks/{task_id}/config",
                    "PATCH",
                    {"max_iterations": 2, "test_commands": ["python -m unittest"]},
                )
                self.assertEqual(status, 200)
                self.assertIsInstance(patched, dict)
                self.assertEqual(patched["config"]["override"]["max_iterations"], 2)
                self.assertEqual(patched["config"]["override"]["test_commands"], ["python -m unittest"])

                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    request(f"/api/tasks/{task_id}", "DELETE", {"confirm": "wrong-id"})
                self.assertEqual(ctx.exception.code, 400)

                status, deleted, _ = request(f"/api/tasks/{task_id}", "DELETE", {"confirm": task_id})
                self.assertEqual(status, 200)
                self.assertIsInstance(deleted, dict)
                self.assertTrue(deleted["deleted"])
                self.assertFalse((root / ".agentloop" / "tasks" / task_id).exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
