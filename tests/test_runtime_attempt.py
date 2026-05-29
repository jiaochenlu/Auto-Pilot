"""Regression tests for the per-agent ``attempt`` field exposed by
``latest_runtime_summary``.

These tests pin AC-08 / AC-10 of the execution-log refactor: the front-end
needs a stable, back-end-assigned attempt index so that the merged (iteration,
role) rows can expose an attempt selector without inferring order from array
position.  The tests run against the real ``latest_runtime_summary`` function
with a minimally-seeded workspace; they intentionally do not boot the HTTP
server or invoke workflows, keeping the surface area to the field contract
itself.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentloop.api import latest_runtime_summary
from agentloop.workspace import init_workspace


def _agent(role: str, *, iteration: int | None, stdout_log: str | None = None,
           exit_code: int | None = 0) -> dict:
    entry: dict = {
        "role": role,
        "runtime": "manual",
        "adapter": "command",
        "command": f"run {role}",
        "exit_code": exit_code,
        "duration_ms": 1000,
        "artifacts": [],
    }
    if iteration is not None:
        entry["iteration"] = iteration
    if stdout_log is not None:
        entry["stdout_log"] = stdout_log
    return entry


class AttemptFieldTests(unittest.TestCase):
    """``latest_runtime_summary`` must annotate each agent entry with an
    ``attempt`` integer that counts up within (iteration, role) buckets.
    """

    def _attempts(self, agents: list[dict], role: str) -> list[int]:
        return [a["attempt"] for a in agents if a.get("role") == role]

    def test_framer_quad_attempt_sequence(self) -> None:
        """AC-08 / T1: four framer entries in the same iteration must yield
        attempt == [1, 2, 3, 4] in state.agents order."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            state = {
                "task_id": "20260528-attempt-quad",
                "iteration": 0,
                "agents": [
                    _agent("framer", iteration=0),
                    _agent("framer", iteration=0),
                    _agent("framer", iteration=0),
                    _agent("framer", iteration=0),
                    _agent("architect", iteration=0),
                ],
            }

            summary = latest_runtime_summary(root, state)
            agents = summary["by_iteration"][0]["agents"]

            self.assertEqual(self._attempts(agents, "framer"), [1, 2, 3, 4])
            self.assertEqual(self._attempts(agents, "architect"), [1])
            for entry in agents:
                self.assertIn("attempt", entry,
                              "every agent entry must carry an attempt field")
                self.assertIsInstance(entry["attempt"], int)
                self.assertGreaterEqual(entry["attempt"], 1)

    def test_tester_pair_attempt_sequence(self) -> None:
        """AC-08 / T1: tester setup + verify share the role bucket and must
        produce attempt == [1, 2]."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            state = {
                "task_id": "20260528-attempt-tester",
                "iteration": 3,
                "agents": [
                    _agent("implementer", iteration=3),
                    _agent("tester", iteration=3),
                    _agent("tester", iteration=3),
                ],
            }

            summary = latest_runtime_summary(root, state)
            agents = summary["by_iteration"][-1]["agents"]
            self.assertEqual(self._attempts(agents, "tester"), [1, 2])
            self.assertEqual(self._attempts(agents, "implementer"), [1])

    def test_missing_iteration_falls_back_to_stdout_log_path(self) -> None:
        """AC-10 / T2: when an agent dict lacks the ``iteration`` key, the
        attempt counter must still bucket by the iteration recovered from the
        ``stdout_log`` NNN segment, and order must follow state.agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            task_id = "20260528-attempt-fallback"
            state = {
                "task_id": task_id,
                "iteration": 1,
                "agents": [
                    _agent("framer", iteration=None,
                           stdout_log=f".agentloop/runs/{task_id}/001/framer.stdout.log"),
                    _agent("framer", iteration=None,
                           stdout_log=f".agentloop/runs/{task_id}/001/framer.stdout.log"),
                    _agent("framer", iteration=None,
                           stdout_log=f".agentloop/runs/{task_id}/001/framer.stdout.log"),
                ],
            }

            summary = latest_runtime_summary(root, state)
            by_iter = {b["iteration"]: b for b in summary["by_iteration"]}
            self.assertIn(1, by_iter,
                          "iteration must be recovered from stdout_log path "
                          "even when agent.iteration is missing")
            self.assertEqual(self._attempts(by_iter[1]["agents"], "framer"),
                             [1, 2, 3])

    def test_attempt_buckets_are_per_iteration(self) -> None:
        """AC-10 / T2 extension: the same role across different iterations
        must each restart its attempt counter at 1, in state.agents order."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            state = {
                "task_id": "20260528-attempt-cross-iter",
                "iteration": 1,
                "agents": [
                    _agent("framer", iteration=0),
                    _agent("framer", iteration=0),
                    _agent("framer", iteration=1),
                    _agent("framer", iteration=1),
                    _agent("framer", iteration=1),
                ],
            }

            summary = latest_runtime_summary(root, state)
            by_iter = {b["iteration"]: b for b in summary["by_iteration"]}
            self.assertEqual(self._attempts(by_iter[0]["agents"], "framer"),
                             [1, 2])
            self.assertEqual(self._attempts(by_iter[1]["agents"], "framer"),
                             [1, 2, 3])

    def test_latest_iteration_agents_carry_attempt(self) -> None:
        """The legacy top-level ``agents`` list (used by callers that ignore
        ``by_iteration``) must also carry the ``attempt`` field — this guards
        AC-09 against silently dropping the new annotation on the alternate
        access path."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            state = {
                "task_id": "20260528-attempt-latest",
                "iteration": 2,
                "agents": [
                    _agent("framer", iteration=2),
                    _agent("framer", iteration=2),
                ],
            }

            summary = latest_runtime_summary(root, state)
            self.assertEqual(self._attempts(summary["agents"], "framer"),
                             [1, 2])


if __name__ == "__main__":
    unittest.main()
