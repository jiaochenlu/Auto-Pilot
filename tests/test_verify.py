from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agentloop.cli import main


class RuntimeVerifyTests(unittest.TestCase):
    def test_runtime_verify_checks_external_artifact_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "verify_agent.py"
            script.write_text(
                "from pathlib import Path\n"
                "Path('.agentloop/artifacts/runtime-verify.txt').write_text('AGENTLOOP_RUNTIME_VERIFY_OK\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])
                main(["--root", str(root), "runtime", "add-command", "fake", "--command", sys.executable, "--arg", str(script)])

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--root", str(root), "runtime", "verify", "fake", "--timeout-seconds", "30"])

            self.assertEqual(exit_code, 0)
            self.assertIn("Runtime verified", output.getvalue())
            self.assertTrue((root / ".agentloop" / "artifacts" / "runtime-verify.txt").exists())

    def test_runtime_verify_rejects_manual_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "init"])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(["--root", str(root), "runtime", "verify", "manual"])

            self.assertEqual(exit_code, 2)
            self.assertIn("Runtime verification requires a command adapter", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
