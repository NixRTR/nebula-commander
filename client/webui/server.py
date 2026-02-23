"""
Local HTTP server for ncclient Web UI. Serves static files and JSON API.
Can be started by the tray (with optional status/polling callbacks) or by `ncclient web`.
"""
import json
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable
from urllib.parse import parse_qs, urlparse

# Ensure client is on path when run as module
def _ensure_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    if root not in sys.path:
        sys.path.insert(0, root)

_ensure_path()

from client.config import load_settings, save_settings, settings_path, token_path
from client.ncclient import _default_output_dir, cmd_enroll


# Default port; override with env NCCLIENT_WEB_PORT
DEFAULT_PORT = 47652


def _get_port() -> int:
    try:
        return int(os.environ.get("NCCLIENT_WEB_PORT", "").strip() or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def _autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        from client.windows import autostart
        return autostart.is_autostart_enabled()
    except Exception:
        return False


def _autostart_set(enabled: bool) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Autostart is only supported on Windows."
    try:
        from client.windows import autostart
        if enabled:
            if getattr(sys, "frozen", False):
                ok = autostart.enable_autostart(sys.executable)
            else:
                # Launcher batch so -m client.windows.tray runs correctly
                appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
                dir_path = os.path.join(appdata, "nebula-commander")
                os.makedirs(dir_path, exist_ok=True)
                bat_path = os.path.join(dir_path, "ncclient-tray-launch.bat")
                repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if not os.path.isfile(pythonw):
                    pythonw = sys.executable
                content = f'@echo off\ncd /d "{repo_root}"\n"{pythonw}" -m client.windows.tray\n'
                with open(bat_path, "w", encoding="utf-8") as f:
                    f.write(content)
                ok = autostart.enable_autostart(bat_path)
            return ok, "Enabled" if ok else "Failed to enable"
        else:
            ok = autostart.disable_autostart()
            return ok, "Disabled" if ok else "Failed to disable"
    except Exception as e:
        return False, str(e)


def _default_nebula_path() -> str:
    try:
        from client.windows import dialogs
        bundled = dialogs.get_bundled_nebula_path()
        if bundled:
            return bundled
    except Exception:
        pass
    # Downloaded path: ~/.config/nebula-commander/nebula/nebula.exe
    nebula_dir = os.path.join(os.path.dirname(token_path()), "nebula")
    exe = os.path.join(nebula_dir, "nebula.exe")
    return exe if os.path.isfile(exe) else "nebula"


class ConfigHandler(BaseHTTPRequestHandler):
    """Serves GET/POST /api/* and static files from webui/static/."""

    def log_message(self, format, *args):
        # Suppress default request logging
        pass

    def _json(self, obj: dict, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode("utf-8"))

    def _read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return None

    def _get_settings_response(self) -> dict:
        s = load_settings()
        server = (s.get("server") or "").strip() or "https://"
        output_dir = (s.get("output_dir") or "").strip() or _default_output_dir()
        interval = int(s.get("interval") or 60)
        if interval < 10:
            interval = 10
        elif interval > 3600:
            interval = 3600
        nebula_path = (s.get("nebula_path") or "").strip() or _default_nebula_path()
        enrolled = os.path.isfile(token_path())
        return {
            "server": server,
            "output_dir": output_dir,
            "interval": interval,
            "nebula_path": nebula_path,
            "enrolled": enrolled,
            "autostart": _autostart_enabled(),
            "platform": sys.platform,
        }

    def _api_get_settings(self) -> None:
        self._json(self._get_settings_response())

    def _api_post_settings(self) -> None:
        body = self._read_json()
        if not body or not isinstance(body, dict):
            self._json({"error": "Invalid JSON"}, 400)
            return
        s = load_settings()
        if "server" in body:
            s["server"] = (body.get("server") or "").strip() or s.get("server", "https://")
        if "output_dir" in body:
            s["output_dir"] = (body.get("output_dir") or "").strip() or _default_output_dir()
        if "interval" in body:
            try:
                i = int(body.get("interval", 60))
                s["interval"] = max(10, min(3600, i))
            except (TypeError, ValueError):
                pass
        if "nebula_path" in body:
            s["nebula_path"] = (body.get("nebula_path") or "").strip()
        save_settings(s)
        self._json(self._get_settings_response())

    def _api_post_enroll(self) -> None:
        body = self._read_json()
        if not body or not isinstance(body, dict):
            self._json({"error": "Invalid JSON"}, 400)
            return
        server = (body.get("server") or "").strip()
        code = (body.get("code") or "").strip().upper()
        if not server:
            self._json({"error": "Server URL required"}, 400)
            return
        if not code:
            self._json({"error": "Enrollment code required"}, 400)
            return
        try:
            cmd_enroll(server, code, None)
            self._json({"ok": True, "message": "Enrolled successfully"})
        except SystemExit as e:
            msg = str(e.code).strip() if isinstance(e.code, str) and str(e.code).strip() else "Enroll failed. Check server URL and code."
            self._json({"error": msg}, 400)
        except Exception as e:
            self._json({"error": str(e)}, 400)

    def _api_get_status(self) -> None:
        get_status = getattr(self.server, "_get_status", None)
        if get_status:
            try:
                status, message = get_status()
                self._json({"polling": status == "connected" or (status != "idle" and status != "error"), "status": status, "message": message})
            except Exception as e:
                self._json({"polling": False, "status": "error", "message": str(e)})
        else:
            self._json({"polling": False, "status": "idle", "message": "Not running from tray"})

    def _api_post_polling(self) -> None:
        body = self._read_json() or {}
        start = body.get("start", True)
        set_polling = getattr(self.server, "_set_polling", None)
        if not set_polling:
            self._json({"error": "Polling control only available when running from tray"}, 409)
            return
        try:
            set_polling(start)
            self._json({"ok": True, "polling": start})
        except Exception as e:
            self._json({"error": str(e)}, 400)

    def _api_get_autostart(self) -> None:
        self._json({"enabled": _autostart_enabled()})

    def _api_post_autostart(self) -> None:
        body = self._read_json()
        if not body or not isinstance(body, dict):
            self._json({"error": "Invalid JSON"}, 400)
            return
        enabled = bool(body.get("enabled", False))
        ok, msg = _autostart_set(enabled)
        self._json({"enabled": _autostart_enabled(), "ok": ok, "message": msg})

    def _serve_static(self, path: str) -> bool:
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        if path in ("", "/"):
            path = "index.html"
        path = path.lstrip("/")
        if ".." in path or path.startswith("/"):
            return False
        full = os.path.normpath(os.path.join(static_dir, path))
        if not full.startswith(os.path.abspath(static_dir)):
            return False
        if not os.path.isfile(full):
            return False
        ext = os.path.splitext(full)[1].lower()
        mime = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".ico": "image/x-icon",
        }.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.end_headers()
        with open(full, "rb") as f:
            self.wfile.write(f.read())
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path.startswith("/api/"):
            self.send_header("Access-Control-Allow-Origin", "*")
            if path == "/api/settings":
                self._api_get_settings()
            elif path == "/api/status":
                self._api_get_status()
            elif path == "/api/autostart":
                self._api_get_autostart()
            else:
                self.send_response(404)
                self.end_headers()
        else:
            if not self._serve_static(path):
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/settings":
            self._api_post_settings()
        elif path == "/api/enroll":
            self._api_post_enroll()
        elif path == "/api/status":
            self.send_response(405)
            self.end_headers()
        elif path == "/api/polling":
            self._api_post_polling()
        elif path == "/api/autostart":
            self._api_post_autostart()
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def run_server(
    port: int | None = None,
    get_status: Callable[[], tuple[str, str]] | None = None,
    set_polling: Callable[[bool], None] | None = None,
) -> tuple[HTTPServer, str]:
    """
    Start the config HTTP server. Returns (server, base_url).
    get_status: optional callback () -> (status, message) for GET /api/status.
    set_polling: optional callback (start: bool) for POST /api/polling.
    """
    port = port or _get_port()
    server = HTTPServer(("127.0.0.1", port), ConfigHandler)
    server._get_status = get_status
    server._set_polling = set_polling
    base_url = f"http://127.0.0.1:{port}"
    return server, base_url


def run_server_thread(
    port: int | None = None,
    get_status: Callable[[], tuple[str, str]] | None = None,
    set_polling: Callable[[bool], None] | None = None,
) -> tuple[threading.Thread, str]:
    """Start the config server in a daemon thread. Returns (thread, base_url)."""
    server, base_url = run_server(port=port, get_status=get_status, set_polling=set_polling)

    def serve() -> None:
        try:
            server.serve_forever()
        finally:
            server.shutdown()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return t, base_url
