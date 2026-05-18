"""Runtime configuration helpers for AgentLoop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .workspace import WorkspaceError, config_path, load_config, write_json


VALID_ROLES = {"analyst", "architect", "implementer", "tester", "reviewer", "integrator"}

RUNTIME_PRESETS: dict[str, dict[str, Any]] = {
    "codex": {
        "adapter": "command",
        "command": "codex",
        "args": ["exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "-"],
        "stdin_file": "{prompt_file}",
    },
    "claude-code": {
        "adapter": "command",
        "command": "claude",
        "args": ["--print", "{prompt_file}"],
    },
    "copilot": {
        "adapter": "command",
        "command": "gh",
        "args": ["copilot", "suggest", "--file", "{prompt_file}"],
    },
    "manual": {
        "adapter": "manual",
        "description": "Write prompts to disk and wait for the user to provide artifacts.",
    },
}


def save_config(root: Path, config: dict[str, Any]) -> None:
    write_json(config_path(root), config)


def list_runtimes(root: Path) -> dict[str, Any]:
    return load_config(root)


def add_command_runtime(
    root: Path,
    name: str,
    command: str,
    args: list[str],
    stdin_file: str | None = None,
    timeout_seconds: int | None = None,
    set_default: bool = False,
    replace: bool = False,
) -> dict[str, Any]:
    runtime_name = name.strip()
    if not runtime_name:
        raise WorkspaceError("Runtime name cannot be empty.")
    if not command.strip():
        raise WorkspaceError("Runtime command cannot be empty.")

    config = load_config(root)
    runtimes = config.setdefault("runtimes", {})
    if runtime_name in runtimes and not replace:
        raise WorkspaceError(f"Runtime already exists: {runtime_name}. Use --replace to overwrite it.")

    runtime: dict[str, Any] = {
        "adapter": "command",
        "command": command,
        "args": args,
    }
    if stdin_file:
        runtime["stdin_file"] = stdin_file
    if timeout_seconds is not None:
        if timeout_seconds <= 0:
            raise WorkspaceError("timeout_seconds must be greater than zero.")
        runtime["timeout_seconds"] = timeout_seconds
    runtimes[runtime_name] = runtime
    if set_default:
        config["default_runtime"] = runtime_name
    save_config(root, config)
    return config


def add_preset_runtime(
    root: Path,
    preset: str,
    assign_roles: list[str] | None = None,
    assign_all: bool = False,
    set_default: bool = False,
    replace: bool = False,
) -> dict[str, Any]:
    preset_name = preset.strip()
    if preset_name not in RUNTIME_PRESETS:
        raise WorkspaceError(f"Unknown preset: {preset}. Available presets: {', '.join(sorted(RUNTIME_PRESETS))}")

    config = load_config(root)
    runtimes = config.setdefault("runtimes", {})
    if preset_name in runtimes and not replace:
        raise WorkspaceError(f"Runtime already exists: {preset_name}. Use --replace to overwrite it.")
    runtimes[preset_name] = dict(RUNTIME_PRESETS[preset_name])

    roles = config.setdefault("roles", {})
    if assign_all:
        for role in sorted(VALID_ROLES):
            roles[role] = {"runtime": preset_name}
    for role in assign_roles or []:
        if role not in VALID_ROLES:
            raise WorkspaceError(f"Unknown role: {role}. Valid roles: {', '.join(sorted(VALID_ROLES))}")
        roles[role] = {"runtime": preset_name}
    if set_default:
        config["default_runtime"] = preset_name
    save_config(root, config)
    return config


def assign_runtime(root: Path, role: str, runtime_name: str) -> dict[str, Any]:
    normalized_role = role.strip()
    if normalized_role not in VALID_ROLES:
        raise WorkspaceError(f"Unknown role: {role}. Valid roles: {', '.join(sorted(VALID_ROLES))}")

    config = load_config(root)
    if runtime_name not in config.get("runtimes", {}):
        raise WorkspaceError(f"Unknown runtime: {runtime_name}")
    config.setdefault("roles", {})[normalized_role] = {"runtime": runtime_name}
    save_config(root, config)
    return config


def assign_all_runtime(root: Path, runtime_name: str, except_roles: list[str] | None = None) -> dict[str, Any]:
    excluded = set(except_roles or [])
    unknown_exclusions = excluded - VALID_ROLES
    if unknown_exclusions:
        raise WorkspaceError(
            f"Unknown role in --except: {', '.join(sorted(unknown_exclusions))}. "
            f"Valid roles: {', '.join(sorted(VALID_ROLES))}"
        )

    config = load_config(root)
    if runtime_name not in config.get("runtimes", {}):
        raise WorkspaceError(f"Unknown runtime: {runtime_name}")

    roles = config.setdefault("roles", {})
    for role in sorted(VALID_ROLES):
        if role in excluded:
            continue
        roles[role] = {"runtime": runtime_name}
    save_config(root, config)
    return config


def set_default_runtime(root: Path, runtime_name: str) -> dict[str, Any]:
    config = load_config(root)
    if runtime_name not in config.get("runtimes", {}):
        raise WorkspaceError(f"Unknown runtime: {runtime_name}")
    config["default_runtime"] = runtime_name
    save_config(root, config)
    return config
