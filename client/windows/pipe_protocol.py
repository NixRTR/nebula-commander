"""
Named-pipe control protocol between the Nebula Commander Windows service
(server, see pipe_server.py) and its clients - the CLI's poll-now nudge
(send_command() below, see client/ncclient.py) and the WinUI 3 app's
PipeClient.cs.

This pipe is the app's ONLY way to read or change service state:
%ProgramData%\\nebula-commander\\ is SYSTEM/Administrators-only (see
installer/windows/Product.wxs), mirroring how the Linux desktop app goes
through client/linux/dbus_server.py rather than touching files.

Single-shot request/response: connect, write one JSON message, read one JSON
response, close.

  request:  {"cmd": "<name>", "args": {...}}           (args optional)
  response: {"ok": true, "result": <any>}
            {"ok": false, "error": "<message>", "code": "<code>"}

Commands are either READ (any local, authenticated caller) or MANAGE
(caller's token must be an *elevated* member of BUILTIN\\Administrators -
see pipe_server._caller_is_elevated_admin). A MANAGE command from anyone
else gets code ERR_ADMIN_REQUIRED.
"""
from __future__ import annotations

import json

PIPE_NAME = r"\\.\pipe\NebulaCommanderControl"

# Big enough for get_config_yaml's (redacted) config plus JSON escaping.
BUFFER_SIZE = 256 * 1024

# --- READ commands ---
CMD_GET_STATUS = "get_status"
CMD_GET_SETTINGS = "get_settings"
CMD_IS_ENROLLED = "is_enrolled"
CMD_GET_AVAILABLE_ROUTES = "get_available_routes"
CMD_GET_ADVERTISED_ROUTES = "get_advertised_routes"
CMD_GET_CONFIG_YAML = "get_config_yaml"
CMD_GET_DNS_CONFIGURED = "get_dns_configured"
CMD_GET_NEBULA_VERSION = "get_nebula_version"
CMD_GET_LATEST_NEBULA_TAG = "get_latest_nebula_tag"
CMD_GET_UPDATE_STATUS = "get_update_status"

# --- MANAGE commands ---
CMD_SET_SETTINGS = "set_settings"
CMD_ENROLL = "enroll"
CMD_ACCEPT_ROUTE = "accept_route"
CMD_REJECT_ROUTE = "reject_route"
CMD_ACCEPT_EXIT_NODE = "accept_exit_node"
CMD_REJECT_EXIT_NODE = "reject_exit_node"
CMD_UPDATE_NEBULA = "update_nebula"
# Re-poll config/certs right now instead of waiting for the next interval tick.
CMD_POLL_NOW = "poll_now"
# Stop the current poll loop and start a fresh one, re-reading settings.json.
CMD_RELOAD_SETTINGS = "reload_settings"
# Automatic updates (client/updates.py, client/windows/updater.py).
CMD_SET_AUTO_UPDATE = "set_auto_update"
CMD_UPDATE_CHECK_NOW = "update_check_now"

ERR_ADMIN_REQUIRED = "administrator_required"
ERR_UNKNOWN_COMMAND = "unknown_command"
ERR_BAD_REQUEST = "bad_request"
ERR_FAILED = "failed"
ERR_UNREACHABLE = "unreachable"


def send_request(cmd: str, args: "dict | None" = None, timeout_ms: int = 3000) -> dict:
    """
    Send one command to the service and return its response dict. Never
    raises: returns {"ok": False, "code": "unreachable", ...} if the service
    isn't installed/running or the pipe can't be reached.
    """
    try:
        import pywintypes
        import win32file
        import win32pipe
    except ImportError:
        return {"ok": False, "code": ERR_UNREACHABLE, "error": "pywin32 not available"}

    try:
        win32pipe.WaitNamedPipe(PIPE_NAME, timeout_ms)
        handle = win32file.CreateFile(
            PIPE_NAME,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None,
        )
        try:
            win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
            payload = {"cmd": cmd}
            if args:
                payload["args"] = args
            win32file.WriteFile(handle, json.dumps(payload).encode("utf-8"))
            _, data = win32file.ReadFile(handle, BUFFER_SIZE)
        finally:
            win32file.CloseHandle(handle)
        return json.loads(data.decode("utf-8"))
    except pywintypes.error as e:
        return {"ok": False, "code": ERR_UNREACHABLE, "error": f"service not reachable: {e}"}
    except Exception as e:
        return {"ok": False, "code": ERR_UNREACHABLE, "error": str(e)}


def send_command(cmd: str, timeout_ms: int = 3000) -> dict:
    """Back-compat wrapper for argument-less commands (the CLI's poll-now nudge)."""
    return send_request(cmd, None, timeout_ms)
