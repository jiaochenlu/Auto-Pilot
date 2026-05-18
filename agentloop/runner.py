"""Local command execution helpers for AgentLoop."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any


def run_test_commands(
    root: Path,
    commands: list[str],
    iteration: int,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    base = root / ".agentloop" / "runs"
    if task_id:
        tests_dir = base / task_id / f"{iteration:03d}" / "tests"
    else:
        tests_dir = base / f"{iteration:03d}" / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    for index, command in enumerate(commands, start=1):
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=root,
            shell=True,
            text=True,
            capture_output=True,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        log_path = tests_dir / f"{index:02d}-test.log"
        log_path.write_text(
            "COMMAND\n"
            f"{command}\n\n"
            "STDOUT\n"
            f"{completed.stdout}\n\n"
            "STDERR\n"
            f"{completed.stderr}\n",
            encoding="utf-8",
        )
        results.append(
            {
                "command": command,
                "exit_code": completed.returncode,
                "duration_ms": duration_ms,
                "log": str(log_path.relative_to(root)).replace("\\", "/"),
            }
        )
    return results
