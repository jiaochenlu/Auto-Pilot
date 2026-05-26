"""Runtime configuration helpers for AgentLoop."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .workspace import WorkspaceError, config_path, load_config, write_json


VALID_ROLES = {"framer", "investigator", "architect", "implementer", "tester", "reviewer", "integrator"}

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


def command_runtime(command: str, args: list[str], stdin_file: str | None = None) -> dict[str, Any]:
    runtime: dict[str, Any] = {
        "adapter": "command",
        "command": command,
        "args": args,
    }
    if stdin_file:
        runtime["stdin_file"] = stdin_file
    return runtime


def existing_file(path: str | Path | None) -> str | None:
    if not path:
        return None
    candidate = Path(path)
    return str(candidate) if candidate.exists() and candidate.is_file() else None


def first_existing(paths: list[str | Path]) -> str | None:
    for path in paths:
        found = existing_file(path)
        if found:
            return found
    return None


def _npm_global_dirs() -> list[Path]:
    """Common locations where `npm -g` installs binaries across platforms."""
    dirs: list[Path] = []
    home = Path.home()
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            dirs.append(Path(appdata) / "npm")
    else:
        # macOS (Homebrew + system) and Linux conventions
        dirs.extend([
            home / ".npm-global" / "bin",
            home / ".local" / "bin",
            Path("/usr/local/bin"),
            Path("/opt/homebrew/bin"),
            Path("/usr/bin"),
        ])
    return dirs


def _npm_global_lib_dirs() -> list[Path]:
    """Common roots for `npm -g` `node_modules/` package payloads."""
    dirs: list[Path] = []
    home = Path.home()
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            dirs.append(Path(appdata) / "npm" / "node_modules")
    else:
        dirs.extend([
            home / ".npm-global" / "lib" / "node_modules",
            Path("/usr/local/lib/node_modules"),
            Path("/opt/homebrew/lib/node_modules"),
            Path("/usr/lib/node_modules"),
        ])
    return dirs


def detect_claude_command() -> str | None:
    found = shutil.which("claude") or shutil.which("claude.exe") or shutil.which("claude.cmd")
    if found:
        return found
    candidates: list[str | Path] = []
    for bin_dir in _npm_global_dirs():
        candidates.extend([
            bin_dir / "claude",
            bin_dir / "claude.cmd",
            bin_dir / "claude.exe",
        ])
    for lib_dir in _npm_global_lib_dirs():
        pkg_bin = lib_dir / "@anthropic-ai" / "claude-code" / "bin"
        candidates.extend([pkg_bin / "claude", pkg_bin / "claude.exe"])
    return first_existing(candidates)


def detect_codex_command() -> str | None:
    found = shutil.which("codex") or shutil.which("codex.exe") or shutil.which("codex.cmd")
    if found:
        return found
    candidates: list[str | Path] = []
    for bin_dir in _npm_global_dirs():
        candidates.extend([
            bin_dir / "codex",
            bin_dir / "codex.cmd",
            bin_dir / "codex.exe",
        ])
    direct = first_existing(candidates)
    if direct:
        return direct
    for lib_dir in _npm_global_lib_dirs():
        vendor_root = lib_dir / "@openai" / "codex"
        if not vendor_root.exists():
            continue
        for name in ("codex", "codex.exe"):
            for candidate in vendor_root.rglob(name):
                return str(candidate)
    return None


def detect_copilot_command() -> str | None:
    return shutil.which("gh") or shutil.which("gh.exe") or shutil.which("gh.cmd")


def detect_runtime_definitions() -> dict[str, dict[str, Any]]:
    detected: dict[str, dict[str, Any]] = {}
    claude = detect_claude_command()
    if claude:
        detected["claude-code"] = command_runtime(
            claude,
            ["--print", "--permission-mode", "acceptEdits"],
            stdin_file="{prompt_file}",
        )
    codex = detect_codex_command()
    if codex:
        detected["codex"] = command_runtime(
            codex,
            ["exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "-"],
            stdin_file="{prompt_file}",
        )
    copilot = detect_copilot_command()
    if copilot:
        detected["copilot"] = command_runtime(copilot, ["copilot", "suggest", "--file", "{prompt_file}"])
    return detected


def save_config(root: Path, config: dict[str, Any]) -> None:
    write_json(config_path(root), config)


def list_runtimes(root: Path) -> dict[str, Any]:
    return load_config(root)


def detect_runtimes(root: Path, replace: bool = False) -> dict[str, Any]:
    config = load_config(root)
    runtimes = config.setdefault("runtimes", {})
    detected = detect_runtime_definitions()
    installed: list[str] = []
    skipped: list[str] = []
    for name, runtime in detected.items():
        if name in runtimes and not replace:
            skipped.append(name)
            continue
        runtimes[name] = runtime
        installed.append(name)
    save_config(root, config)
    return {"config": config, "detected": detected, "installed": installed, "skipped": skipped}


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
