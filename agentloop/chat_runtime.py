"""Runtime invocation for the Chat module.

We reuse the runtime configuration from .agentloop/config.json (same runtimes
that power Task roles), but the calling convention is simpler: build a single
prompt from the conversation history, write it to disk, run the runtime CLI
with `{prompt_file}` / `{prompt_text}` substitution, and capture stdout as the
assistant reply.

Two entry points:
- send_message(): blocking, returns final state. Used by REST callers/tests.
- stream_message(): generator yielding (event_type, payload) tuples for SSE.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Iterator

from . import chats
from .adapters import render_args
from .sessions import extract_session_id, runtime_supports_resume
from .workspace import WorkspaceError, load_config


def _resolve_runtime(root: Path, runtime_name: str) -> dict[str, Any]:
    config = load_config(root)
    runtimes = config.get("runtimes", {}) if isinstance(config, dict) else {}
    runtime = runtimes.get(runtime_name)
    if not isinstance(runtime, dict):
        raise WorkspaceError(f"Runtime not configured: {runtime_name}")
    return runtime


def build_prompt(state: dict[str, Any], user_message: str) -> str:
    """Render the full conversation as a single prompt string.

    The runtime CLI gets the entire history each turn. For runtimes that
    support `resume_args` (e.g. claude-code with --resume), we'll pass only
    the latest user message in `prompt_text`; otherwise we pass the full
    transcript.
    """

    lines: list[str] = []
    system = (state.get("system_prompt") or "").strip()
    if system:
        lines.append(f"[system]\n{system}\n")

    messages = state.get("messages") or []
    compact_summary = (state.get("compact_summary") or "").strip()
    compact_up_to = state.get("compact_up_to_message_id")
    start_idx = 0
    if compact_summary and compact_up_to:
        for i, msg in enumerate(messages):
            if msg.get("id") == compact_up_to:
                start_idx = i + 1
                break
        lines.append(f"[context from earlier in this chat — compacted summary]\n{compact_summary}\n")

    for msg in messages[start_idx:]:
        role = msg.get("role")
        content = str(msg.get("content") or "").rstrip()
        if role == "user":
            lines.append(f"[user]\n{content}\n")
        elif role == "assistant":
            lines.append(f"[assistant]\n{content}\n")
    lines.append(f"[user]\n{user_message.rstrip()}\n")
    lines.append("[assistant]\n")
    return "\n".join(lines)


def run_one_shot(root: Path, chat_id: str, runtime_name: str, prompt_text: str,
                 *, label: str = "oneshot") -> str:
    """Invoke a runtime synchronously with a single prompt and return stdout.

    Used for meta operations like compact/summarize that don't belong in the
    user-visible message history. Bypasses chat state mutation and session
    resume — always starts a fresh runtime invocation.
    """

    runtime = _resolve_runtime(root, runtime_name)
    adapter = runtime.get("adapter", "command")
    if adapter == "manual":
        raise WorkspaceError("Manual runtime cannot be invoked for compact.")
    if adapter != "command":
        raise WorkspaceError(f"Unsupported adapter for compact: {adapter}")
    command = runtime.get("command")
    if not command:
        raise WorkspaceError(f"Command runtime {runtime_name} is missing `command`.")

    prompt_path = chats.chat_dir(root, chat_id) / "prompts" / f"{label}.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt_text, encoding="utf-8")

    values = {
        "cwd": str(root),
        "role": "chat",
        "iteration": label,
        "prompt_file": str(prompt_path),
        "prompt_text": prompt_text,
        "session_id": "",
        "task_id": chat_id,
    }
    base_args = list(runtime.get("args") or [])
    extra_args = list(runtime.get("new_session_args") or [])
    argv = [command, *render_args([*base_args, *extra_args], values)]

    stdin_text: str | None = None
    stdin_file = runtime.get("stdin_file")
    if stdin_file:
        stdin_path = Path(render_args([str(stdin_file)], values)[0])
        if not stdin_path.is_absolute():
            stdin_path = root / stdin_path
        if stdin_path.exists():
            stdin_text = stdin_path.read_text(encoding="utf-8")

    state = chats.load_chat_state(root, chat_id)
    working_dir = state.get("working_dir") or ""
    cwd = Path(working_dir) if working_dir else root
    if not cwd.is_absolute():
        cwd = (root / cwd).resolve()

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    timeout = runtime.get("timeout_seconds")

    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            input=stdin_text if stdin_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise WorkspaceError(f"Runtime command not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired:
        raise WorkspaceError(f"Runtime timed out after {timeout}s")

    if result.returncode != 0:
        raise WorkspaceError(
            f"Runtime exited {result.returncode}: {(result.stderr or '').strip()[:500]}"
        )
    return (result.stdout or "").strip()


def send_message(root: Path, chat_id: str, user_content: str) -> dict[str, Any]:
    """Blocking convenience wrapper around stream_message().

    Drives the generator to completion and returns the final chat state.
    """
    final: dict[str, Any] | None = None
    for event, payload in stream_message(root, chat_id, user_content):
        if event == "done":
            final = payload.get("state")
        elif event == "error":
            raise WorkspaceError(payload.get("message") or "Chat runtime error")
    if final is None:
        final = chats.load_chat_state(root, chat_id)
    return final


def _prepare_turn(root: Path, chat_id: str, user_content: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str], Path | None, str | None, int | None, Path]:
    """Validate runtime + append user message + render args. Returns
    (state, runtime, user_msg, argv, cwd, stdin_text, timeout, stderr_log_path).

    Raises WorkspaceError on misconfiguration. Caller must handle subprocess
    lifecycle and writing stdout log.
    """

    state = chats.load_chat_state(root, chat_id)
    runtime_name = state.get("runtime") or "manual"
    runtime = _resolve_runtime(root, runtime_name)
    adapter = runtime.get("adapter", "command")

    user_msg = chats.append_message(state, "user", user_content)
    chats.maybe_autotitle(state)
    chats.save_chat_state(root, chat_id, state)

    if adapter == "manual":
        state["status"] = "waiting_manual"
        chats.save_chat_state(root, chat_id, state)
        raise WorkspaceError("Manual runtime requires a human reply.")
    if adapter != "command":
        raise WorkspaceError(f"Unsupported adapter for chat: {adapter}")

    turn = len([m for m in state["messages"] if m.get("role") == "user"])
    session_id = state.get("session_id")
    resuming = bool(session_id) and runtime_supports_resume(runtime)

    if resuming:
        prompt_text = user_content
    else:
        prompt_text = build_prompt({**state, "messages": state["messages"][:-1]}, user_content)

    prompt_path = chats.chat_prompt_path(root, chat_id, turn)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt_text, encoding="utf-8")

    stdout_log, stderr_log = chats.chat_run_log_paths(root, chat_id, turn)

    command = runtime.get("command")
    if not command:
        raise WorkspaceError(f"Command runtime {runtime_name} is missing `command`.")

    values = {
        "cwd": str(root),
        "role": "chat",
        "iteration": str(turn),
        "prompt_file": str(prompt_path),
        "prompt_text": prompt_text,
        "session_id": session_id or "",
        "task_id": chat_id,
    }
    base_args = list(runtime.get("args") or [])
    extra_args = list(runtime.get("resume_args") if resuming else runtime.get("new_session_args") or [])
    argv = [command, *render_args([*base_args, *extra_args], values)]

    stdin_text: str | None = None
    stdin_file = runtime.get("stdin_file")
    if stdin_file:
        stdin_path = Path(render_args([str(stdin_file)], values)[0])
        if not stdin_path.is_absolute():
            stdin_path = root / stdin_path
        if stdin_path.exists():
            stdin_text = stdin_path.read_text(encoding="utf-8")

    working_dir = state.get("working_dir") or ""
    cwd = Path(working_dir) if working_dir else root
    if not cwd.is_absolute():
        cwd = (root / cwd).resolve()

    return state, runtime, user_msg, argv, cwd, stdin_text, runtime.get("timeout_seconds"), stdout_log


def stream_message(root: Path, chat_id: str, user_content: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Drive a chat turn as a stream of events.

    Yields tuples (event_type, payload):
      ("user_message", {"message": <msg>})  -- right after user msg saved
      ("chunk", {"delta": str})             -- each chunk of runtime stdout
      ("done",  {"state": <chat_state>})    -- final state after assistant saved
      ("error", {"message": str})           -- terminal error (also closes stream)
    """

    runtime_name: str | None = None
    try:
        prep = _prepare_turn(root, chat_id, user_content)
    except WorkspaceError as exc:
        yield ("error", {"message": str(exc)})
        return

    state, runtime, user_msg, argv, cwd, stdin_text, timeout, stdout_log = prep
    runtime_name = state.get("runtime")
    turn = len([m for m in state["messages"] if m.get("role") == "user"]) - 1
    # ^^ turn index that matches the prompt file we just wrote
    turn = max(0, turn)
    stderr_log = stdout_log.with_name(stdout_log.name.replace(".stdout.", ".stderr."))

    yield ("user_message", {"message": user_msg})

    state["status"] = "streaming"
    chats.save_chat_state(root, chat_id, state)

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError as exc:
        state["status"] = "error"
        state["last_error"] = f"Runtime command not found: {argv[0]}"
        chats.save_chat_state(root, chat_id, state)
        stderr_log.write_text(str(exc), encoding="utf-8")
        yield ("error", {"message": state["last_error"]})
        return

    if stdin_text is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin_text)
            proc.stdin.close()
        except Exception:
            pass

    collected: list[str] = []
    deadline = started + timeout if timeout else None
    cancelled = False
    try:
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.readline()
            if not chunk:
                if proc.poll() is not None:
                    break
                if deadline and time.monotonic() > deadline:
                    proc.kill()
                    raise subprocess.TimeoutExpired(argv[0], timeout)
                continue
            collected.append(chunk)
            yield ("chunk", {"delta": chunk})
    except GeneratorExit:
        # Consumer (HTTP handler) closed the generator — typically because the
        # client disconnected or hit Stop. Kill the subprocess, persist what
        # we collected as a partial assistant message, then propagate.
        cancelled = True
        if proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
        stderr_text = ""
        try:
            stderr_text = proc.stderr.read() if proc.stderr else ""
        except Exception:
            pass
        partial = "".join(collected)
        stdout_log.write_text(partial, encoding="utf-8")
        stderr_log.write_text(stderr_text or "", encoding="utf-8")
        reply = partial.strip() or "(cancelled before any output)"
        chats.append_message(
            state,
            "assistant",
            reply,
            meta={
                "runtime": runtime_name,
                "turn": turn,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "cancelled": True,
            },
        )
        state["status"] = "idle"
        state["last_error"] = "Cancelled by user."
        chats.save_chat_state(root, chat_id, state)
        raise
    except subprocess.TimeoutExpired as exc:
        state["status"] = "error"
        state["last_error"] = f"Runtime timed out after {timeout}s"
        chats.save_chat_state(root, chat_id, state)
        stderr_log.write_text(str(exc), encoding="utf-8")
        yield ("error", {"message": state["last_error"]})
        return

    if cancelled:
        return

    rc = proc.wait()
    stderr_text = proc.stderr.read() if proc.stderr else ""
    stdout_text = "".join(collected)
    stdout_log.write_text(stdout_text, encoding="utf-8")
    stderr_log.write_text(stderr_text or "", encoding="utf-8")

    if rc != 0:
        state["status"] = "error"
        state["last_error"] = (
            f"Runtime exited {rc}. "
            f"See .agentloop/chats/{chat_id}/runs/{turn:03d}.stderr.log"
        )
        chats.save_chat_state(root, chat_id, state)
        yield ("error", {"message": state["last_error"]})
        return

    new_session_id = extract_session_id(runtime, stdout_text, stderr_text)
    if new_session_id:
        state["session_id"] = new_session_id

    reply = stdout_text.strip() or "(runtime produced empty output)"
    duration_ms = int((time.monotonic() - started) * 1000)
    chats.append_message(
        state,
        "assistant",
        reply,
        meta={
            "runtime": runtime_name,
            "turn": turn,
            "duration_ms": duration_ms,
            "session_id": state.get("session_id"),
        },
    )
    state["status"] = "idle"
    state["last_error"] = None
    chats.save_chat_state(root, chat_id, state)
    yield ("done", {"state": state})
