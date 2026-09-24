"""
status.json read/write - the service's self-reported state (state/message/
updated_at), shared with whatever GUI is watching it (the Windows app,
the Linux desktop app via client/linux/dbus_server.py's GetStatus). Pure,
path-parameterized logic with no platform knowledge of its own -
client/windows/shared_paths.py resolves its own shared_root()/status_path()
and calls these directly; client/ncclient.py's cmd_run does the same for
Linux (its output_dir is already the correct shared location, e.g.
/var/lib/ncclient for the packaged systemd service - no separate
shared_paths module needed there since the D-Bus service is what mediates
access for the desktop app, not a shared-permissions directory).
"""
from __future__ import annotations

import datetime
import json
import os

__all__ = ["load_status", "save_status"]

_UNKNOWN_STATUS = {"state": "unknown", "message": "Service not reachable", "updated_at": None}


def load_status(path: str) -> dict:
    """Read the service's last-reported status. Returns a placeholder dict if
    the service has never run or the file can't be read (e.g. not installed)."""
    if not os.path.isfile(path):
        return dict(_UNKNOWN_STATUS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(_UNKNOWN_STATUS)


def save_status(path: str, state: str, message: str, **extra) -> None:
    """Written by the service on every status change; read by the GUI on a
    timer. Written atomically (temp file + rename) so a reader never sees a
    half-written file. Caller is responsible for ensuring path's directory
    already exists (platform-specific permissions/ownership requirements
    live in each platform's own setup - client/windows/shared_paths.py, or
    the systemd unit/tmpfiles.d rule on Linux - not here)."""
    data = {
        "state": state,
        "message": message,
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    data.update(extra)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
