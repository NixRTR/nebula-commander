"""
Windows service-mode paths and activation.

Everything the Nebula Commander Windows service (service.py) and the tray
(tray.py) need to share lives under %ProgramData%\\nebula-commander\\ instead of
today's per-user %APPDATA%/%USERPROFILE% locations, so a LocalSystem service and
an unelevated tray process can both read/write it. The installer creates this
folder at install time with an ACL granting local Users/Authenticated Users
modify rights (see installer/windows/Product.wxs).

Call enable_shared_mode() once, early, before touching anything from
client.config/client.token_store/client.ncclient: it sets the
NEBULA_COMMANDER_CONFIG_DIR environment variable, which client/config.py's
config_dir() and client/token_store.py's Windows token storage both check and
redirect to when present. This means run_poll_loop(), cmd_enroll(), and every
other existing function that goes through config_dir()/token_store need no
changes themselves - they transparently start reading/writing the shared,
machine-wide location once this has been called.

client/config.py and client/token_store.py stay untouched in their default
(no env var set) behavior - the plain cross-platform CLI and Linux/macOS are
unaffected by any of this.
"""
from __future__ import annotations

import datetime
import json
import os

__all__ = [
    "ENV_VAR",
    "shared_root",
    "enable_shared_mode",
    "status_path",
    "load_status",
    "save_status",
]

ENV_VAR = "NEBULA_COMMANDER_CONFIG_DIR"


def shared_root() -> str:
    """%ProgramData%\\nebula-commander\\ - created by the installer with a shared ACL."""
    program_data = (
        os.environ.get("ProgramData")
        or os.environ.get("ALLUSERSPROFILE")
        or r"C:\ProgramData"
    )
    return os.path.join(program_data, "nebula-commander")


def enable_shared_mode() -> str:
    """
    Point client.config.config_dir() (and, transitively, client.token_store's
    Windows token storage) at the shared %ProgramData% root instead of the
    per-user default. Call this once, early, before any settings/token/config
    access. Returns the shared root path.
    """
    root = shared_root()
    os.makedirs(root, exist_ok=True)
    os.environ[ENV_VAR] = root
    return root


def status_path() -> str:
    return os.path.join(shared_root(), "status.json")


def load_status() -> dict:
    """Read the service's last-reported status. Returns a placeholder dict if the
    service has never run or the file can't be read (e.g. service not installed)."""
    path = status_path()
    if not os.path.isfile(path):
        return {"state": "unknown", "message": "Service not reachable", "updated_at": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"state": "unknown", "message": "Service not reachable", "updated_at": None}


def save_status(state: str, message: str, **extra) -> None:
    """Written by the service on every status change; read by the tray on a timer.
    Written atomically (write to a temp file, then replace) so the tray never reads
    a half-written file."""
    root = shared_root()
    os.makedirs(root, exist_ok=True)
    data = {
        "state": state,
        "message": message,
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    data.update(extra)
    path = status_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
