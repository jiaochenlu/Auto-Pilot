from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from agentloop.cli import main


class PhaseOneCliTests(unittest.TestCase):
    def test_init_creates_workspace_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "init"])

            self.assertEqual(exit_code, 0)
            self.assertTrue((root / ".agentloop" / "config.json").exists())
            self.assertTrue((root / ".agentloop" / "state.json").exists())
            self.assertTrue((root / ".agentloop" / "prompts" / "architect.md").exists())
            self.assertTrue((root / ".agentloop" / "artifacts").is_dir())
            self.assertTrue((root / ".agentloop" / "runs").is_dir())
            self.assertTrue((root / ".agentloop" / "locks").is_dir())

            config = json.loads((root / ".agentloop" / "config.json").read_text(encoding="utf-8"))
            state = json.loads((root / ".agentloop" / "state.json").read_text(encoding="utf-8"))

            self.assertEqual(config["default_runtime"], "manual")
            self.assertIn("manual", config["runtimes"])
            self.assertEqual(state["status"], "CREATED")
            self.assertEqual(state["iteration"], 0)

    def test_status_prints_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_output = io.StringIO()
            with redirect_stdout(init_output):
                main(["--root", str(root), "init"])

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "status"])

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("AgentLoop status", text)
            self.assertIn("status: CREATED", text)
            self.assertIn("default_runtime: manual", text)
            self.assertIn("agentloop start", text)


if __name__ == "__main__":
    unittest.main()
