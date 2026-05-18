"""Runtime verification helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import run_command_role
from .workspace import WorkspaceError, agentloop_path, load_config, write_text


VERIFY_ROLE = "verify"
VERIFY_ARTIFACT = ".agentloop/artifacts/runtime-verify.txt"


def verify_runtime(root: Path, runtime_name: str, timeout_seconds: int | None = None) -> dict[str, Any]:
    config = load_config(root)
    runtime = config.get("runtimes", {}).get(runtime_name)
    if not isinstance(runtime, dict):
        raise WorkspaceError(f"Unknown runtime: {runtime_name}")
    if runtime.get("adapter", "command") != "command":
        raise WorkspaceError(f"Runtime verification requires a command adapter: {runtime_name}")

    verify_dir = agentloop_path(root) / "verify"
    verify_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = agentloop_path(root) / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    artifact = root / VERIFY_ARTIFACT
    if artifact.exists():
        artifact.unlink()

    write_text(
        prompts_dir / f"{VERIFY_ROLE}.md",
        "# AgentLoop Runtime Verification\n\n"
        f"Create this exact file: `{VERIFY_ARTIFACT}`.\n\n"
        "The file content must include the text: `AGENTLOOP_RUNTIME_VERIFY_OK`.\n",
    )

    runtime_copy = dict(runtime)
    if timeout_seconds is not None:
        runtime_copy["timeout_seconds"] = timeout_seconds

    result = run_command_role(
        root=root,
        runtime_name=runtime_name,
        runtime=runtime_copy,
        role=VERIFY_ROLE,
        iteration=0,
        required_artifacts=[VERIFY_ARTIFACT],
    )
    content = artifact.read_text(encoding="utf-8")
    if "AGENTLOOP_RUNTIME_VERIFY_OK" not in content:
        raise WorkspaceError(f"Runtime produced {VERIFY_ARTIFACT}, but verification marker is missing.")
    return result
