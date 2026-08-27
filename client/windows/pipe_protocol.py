"""
Named-pipe control protocol between the Nebula Commander Windows service
(server, see service.py) and the tray (client, see tray.py).

Single-shot request/response: connect, write one JSON message, read one JSON
response, close. Status flows the other direction via the shared status.json
file (shared_paths.py), not this pipe - the pipe only carries small imperative
commands that need to happen immediately rather than waiting for the service's
own next poll cycle.
"""
from __future__ import annotations

import json

PIPE_NAME = r"\\.\pipe\NebulaCommanderControl"

# Re-poll config/certs right now instead of waiting for the next interval tick
# (sent after enroll, or after changing settings/the Nebula binary path).
CMD_POLL_NOW = "poll_now"
# Alias kept distinct from CMD_POLL_NOW for readability at call sites even though
# the service currently handles both identically (stop the current poll loop and
# start a fresh one, which re-reads settings.json).
CMD_RELOAD_SETTINGS = "reload_settings"


def send_command(cmd: str, timeout_ms: int = 3000) -> dict:
    """
    Send a command to the service over the named pipe and return its response.
    Returns {"ok": False, "error": "..."} (never raises) if the service isn't
    installed, isn't running, or the pipe otherwise can't be reached - callers
    should treat that as non-fatal: the service will pick up the change on its
    own next poll cycle regardless.
    """
    try:
        import pywintypes
        import win32file
        import win32pipe
    except ImportError:
        return {"ok": False, "error": "pywin32 not available"}

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
            win32file.WriteFile(handle, json.dumps({"cmd": cmd}).encode("utf-8"))
            _, data = win32file.ReadFile(handle, 4096)
        finally:
            win32file.CloseHandle(handle)
        return json.loads(data.decode("utf-8"))
    except pywintypes.error as e:
        return {"ok": False, "error": f"service not reachable: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
