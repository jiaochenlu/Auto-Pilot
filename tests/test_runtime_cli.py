from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agentloop.cli import main


class RuntimeCliTests(unittest.TestCase):
    def test_runtime_add_command_assign_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "init"]), 0)

            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--root",
                        str(root),
                        "runtime",
                        "add-command",
                        "fake",
                        "--command",
                        "python",
                        "--arg",
                        "fake_agent.py",
                        "--arg",
                        "{prompt_file}",
                        "--timeout-seconds",
                        "60",
                        "--set-default",
                    ]
                )
            self.assertEqual(exit_code, 0)

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "runtime", "assign", "implementer", "fake"]), 0)

            config = json.loads((root / ".agentloop" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["default_runtime"], "fake")
            self.assertEqual(config["runtimes"]["fake"]["adapter"], "command")
            self.assertEqual(config["runtimes"]["fake"]["command"], "python")
            self.assertEqual(config["runtimes"]["fake"]["args"], ["fake_agent.py", "{prompt_file}"])
            self.assertEqual(config["runtimes"]["fake"]["timeout_seconds"], 60)
            self.assertEqual(config["roles"]["implementer"]["runtime"], "fake")

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--root", str(root), "runtime", "list"]), 0)
            text = output.getvalue()
            self.assertIn("default_runtime: fake", text)
            self.assertIn("fake: adapter=command command=python", text)
            self.assertIn("implementer: fake", text)

    def test_runtime_set_default_requires_existing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(["--root", str(root), "runtime", "set-default", "missing"])

            self.assertEqual(exit_code, 2)
            self.assertIn("Unknown runtime: missing", stderr.getvalue())

    def test_runtime_assign_validates_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(["--root", str(root), "runtime", "assign", "unknown", "manual"])

            self.assertEqual(exit_code, 2)
            self.assertIn("Unknown role: unknown", stderr.getvalue())

    def test_runtime_assign_all_updates_every_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                main(["--root", str(root), "runtime", "add-command", "codex", "--command", "codex"])

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "runtime", "assign-all", "codex"])

            self.assertEqual(exit_code, 0)
            self.assertIn("Runtime assigned to roles", output.getvalue())
            config = json.loads((root / ".agentloop" / "config.json").read_text(encoding="utf-8"))
            self.assertTrue(all(role["runtime"] == "codex" for role in config["roles"].values()))

    def test_runtime_assign_all_can_exclude_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                main(["--root", str(root), "runtime", "add-command", "codex", "--command", "codex"])
                main(["--root", str(root), "runtime", "assign-all", "codex", "--except", "reviewer"])

            config = json.loads((root / ".agentloop" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["roles"]["implementer"]["runtime"], "codex")
            self.assertEqual(config["roles"]["reviewer"]["runtime"], "manual")

    def test_runtime_add_command_accepts_args_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                exit_code = main(
                    [
                        "--root",
                        str(root),
                        "runtime",
                        "add-command",
                        "codex",
                        "--command",
                        "codex",
                        "--args",
                        "exec --prompt-file {prompt_file}",
                        "--stdin-file",
                        "{prompt_file}",
                    ]
                )

            self.assertEqual(exit_code, 0)
            config = json.loads((root / ".agentloop" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["runtimes"]["codex"]["args"], ["exec", "--prompt-file", "{prompt_file}"])
            self.assertEqual(config["runtimes"]["codex"]["stdin_file"], "{prompt_file}")

    def test_runtime_add_preset_can_assign_all_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                exit_code = main(["--root", str(root), "runtime", "add-preset", "codex", "--assign-all", "--replace"])

            self.assertEqual(exit_code, 0)
            config = json.loads((root / ".agentloop" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["runtimes"]["codex"]["command"], "codex")
            self.assertEqual(config["runtimes"]["codex"]["args"], ["exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "-"])
            self.assertEqual(config["runtimes"]["codex"]["stdin_file"], "{prompt_file}")
            self.assertTrue(all(role["runtime"] == "codex" for role in config["roles"].values()))

    def test_runtime_add_preset_rejects_unknown_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(["--root", str(root), "runtime", "add-preset", "missing"])

            self.assertEqual(exit_code, 2)
            self.assertIn("Unknown preset: missing", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
