from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from agentloop.adapters import run_role
from agentloop.workspace import WorkspaceError, init_workspace


class AdapterTests(unittest.TestCase):
    def test_command_adapter_runs_external_role_and_validates_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)

            script = root / "fake_agent.py"
            script.write_text(
                "from pathlib import Path\n"
                "Path('.agentloop/artifacts/design.md').write_text('# External Design\\n', encoding='utf-8')\n"
                "print('done')\n",
                encoding="utf-8",
            )
            config = {
                "runtimes": {
                    "fake": {
                        "adapter": "command",
                        "command": sys.executable,
                        "args": [str(script)],
                    }
                },
                "roles": {"architect": {"runtime": "fake"}},
            }

            result = run_role(root, config, "architect", 1, [".agentloop/artifacts/design.md"])

            self.assertEqual(result["adapter"], "command")
            self.assertEqual(result["exit_code"], 0)
            self.assertTrue((root / ".agentloop" / "artifacts" / "design.md").exists())
            self.assertTrue((root / result["stdout_log"]).exists())
            self.assertIn("done", (root / result["stdout_log"]).read_text(encoding="utf-8"))

    def test_manual_adapter_records_prompt_and_expected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            config = json.loads((root / ".agentloop" / "config.json").read_text(encoding="utf-8"))

            result = run_role(root, config, "tester", 1, [".agentloop/artifacts/test-plan.md"])

            self.assertEqual(result["adapter"], "manual")
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["artifacts"], [".agentloop/artifacts/test-plan.md"])
            self.assertTrue((root / result["stdout_log"]).exists())

    def test_command_adapter_reports_missing_command_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            config = {
                "runtimes": {
                    "missing": {
                        "adapter": "command",
                        "command": "definitely-missing-agentloop-command",
                        "args": [],
                    }
                },
                "roles": {"architect": {"runtime": "missing"}},
            }

            with self.assertRaises(WorkspaceError) as raised:
                run_role(root, config, "architect", 1, [])

            self.assertIn("Runtime command not found", str(raised.exception))

    def test_command_adapter_can_pipe_prompt_file_to_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            script = root / "stdin_agent.py"
            script.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "data = sys.stdin.read()\n"
                "Path('.agentloop/artifacts/design.md').write_text(data, encoding='utf-8')\n",
                encoding="utf-8",
            )
            (root / ".agentloop" / "prompts" / "architect.md").write_text("PROMPT_FROM_STDIN", encoding="utf-8")
            config = {
                "runtimes": {
                    "stdin": {
                        "adapter": "command",
                        "command": sys.executable,
                        "args": [str(script)],
                        "stdin_file": "{prompt_file}",
                    }
                },
                "roles": {"architect": {"runtime": "stdin"}},
            }

            run_role(root, config, "architect", 1, [".agentloop/artifacts/design.md"])

            self.assertEqual((root / ".agentloop" / "artifacts" / "design.md").read_text(encoding="utf-8"), "PROMPT_FROM_STDIN")

    def test_command_adapter_uses_utf8_for_non_ascii_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            script = root / "utf8_stdin_agent.py"
            script.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "data = sys.stdin.read()\n"
                "Path('.agentloop/artifacts/design.md').write_text(data, encoding='utf-8')\n",
                encoding="utf-8",
            )
            expected = "中文任务：做一个美丽的网站"
            (root / ".agentloop" / "prompts" / "architect.md").write_text(expected, encoding="utf-8")
            config = {
                "runtimes": {
                    "stdin": {
                        "adapter": "command",
                        "command": sys.executable,
                        "args": [str(script)],
                        "stdin_file": "{prompt_file}",
                    }
                },
                "roles": {"architect": {"runtime": "stdin"}},
            }

            run_role(root, config, "architect", 1, [".agentloop/artifacts/design.md"])

            self.assertEqual((root / ".agentloop" / "artifacts" / "design.md").read_text(encoding="utf-8"), expected)


if __name__ == "__main__":
    unittest.main()
