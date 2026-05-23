"""Local HTTP server for the AgentLoop Task Console."""

from __future__ import annotations

import json
import mimetypes
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import api
from .locks import LockHeld
from .workspace import WorkspaceError


STATIC_DIR = Path(__file__).with_name("ui_static")


class AgentLoopUIHandler(BaseHTTPRequestHandler):
    server_version = "AgentLoopUI/1.0"

    @property
    def root(self) -> Path:
        return self.server.root  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}", file=sys.stderr)

    def _send_json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkspaceError(f"Invalid JSON payload: {exc}") from exc
        if not isinstance(payload, dict):
            raise WorkspaceError("JSON payload must be an object.")
        return payload

    def _handle_error(self, exc: Exception) -> None:
        if isinstance(exc, LockHeld):
            self._send_json(409, api.error_payload(exc))
        elif isinstance(exc, WorkspaceError):
            message = str(exc).lower()
            status = 404 if "not found" in message or "does not exist" in message else 400
            self._send_json(status, api.error_payload(exc))
        else:
            print(f"unexpected ui error: {exc}", file=sys.stderr)
            self._send_json(500, {"error": {"code": "internal_error", "message": "Unexpected server error."}})

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/tasks":
                self._send_json(200, api.build_task_list(self.root))
                return
            if path == "/api/settings":
                self._send_json(200, api.build_settings(self.root))
                return
            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                self._send_json(200, api.build_task_detail(self.root, parts[2]))
                return
            if len(parts) == 5 and parts[:2] == ["api", "tasks"] and parts[3] == "artifacts":
                self._send_json(200, api.read_artifact(self.root, parts[2], parts[4]))
                return
            self._serve_static(path)
        except Exception as exc:
            self._handle_error(exc)

    def do_POST(self) -> None:
        try:
            parts = [unquote(part) for part in urlparse(self.path).path.split("/") if part]
            payload = self._read_json()
            if parts == ["api", "tasks"]:
                self._send_json(201, api.create_task(self.root, payload))
                return
            if len(parts) == 4 and parts[:2] == ["api", "tasks"]:
                task_id, op = parts[2], parts[3]
                if op == "approve":
                    self._send_json(200, api.approve_task_api(self.root, task_id, payload))
                    return
                if op == "analysis-review":
                    self._send_json(200, api.submit_analysis_review_api(self.root, task_id, payload))
                    return
                if op == "cancel":
                    self._send_json(200, api.cancel_task_api(self.root, task_id, payload))
                    return
                if op == "run":
                    self._send_json(200, api.run_task_api(self.root, task_id, payload))
                    return
                if op == "resume":
                    self._send_json(200, api.resume_task_api(self.root, task_id, payload))
                    return
            self._send_json(404, {"error": {"code": "not_found", "message": "Endpoint not found."}})
        except Exception as exc:
            self._handle_error(exc)

    def do_PATCH(self) -> None:
        try:
            parts = [unquote(part) for part in urlparse(self.path).path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["api", "tasks"] and parts[3] == "config":
                self._send_json(200, api.patch_task_config(self.root, parts[2], self._read_json()))
                return
            self._send_json(404, {"error": {"code": "not_found", "message": "Endpoint not found."}})
        except Exception as exc:
            self._handle_error(exc)

    def do_DELETE(self) -> None:
        try:
            parts = [unquote(part) for part in urlparse(self.path).path.split("/") if part]
            if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                self._send_json(200, api.delete_task(self.root, parts[2], self._read_json()))
                return
            self._send_json(404, {"error": {"code": "not_found", "message": "Endpoint not found."}})
        except Exception as exc:
            self._handle_error(exc)

    def _serve_static(self, request_path: str) -> None:
        name = "index.html" if request_path in {"/", ""} else request_path.lstrip("/")
        if ".." in Path(name).parts:
            self.send_error(404)
            return
        path = (STATIC_DIR / name).resolve()
        if not str(path).lower().startswith(str(STATIC_DIR.resolve()).lower()) or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix == ".js":
            content_type = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    class Server(ThreadingHTTPServer):
        pass

    server = Server((host, port), AgentLoopUIHandler)
    server.root = root.resolve()  # type: ignore[attr-defined]
    url = f"http://{host}:{server.server_port}"
    print(f"AgentLoop Task Console: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAgentLoop UI stopped.")
    finally:
        server.server_close()
