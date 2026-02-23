"""
Shared config and paths for ncclient (tray, Web UI, CLI).
Settings are stored in settings.json; token path is from ncclient.
"""
import json
import os
import sys

__all__ = ["settings_path", "load_settings", "save_settings", "token_path"]


def token_path() -> str:
    """Path to the device token file (enrollment)."""
    from client.ncclient import _token_path
    return _token_path()


def settings_path() -> str:
    """Path to settings.json (server, output_dir, interval, nebula_path)."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(appdata, "nebula-commander", "settings.json")
    return os.path.join(os.path.dirname(token_path()), "settings.json")


def load_settings() -> dict:
    """Load settings from disk. Returns dict with server, output_dir, interval, nebula_path (or empty)."""
    path = settings_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(settings: dict) -> None:
    """Write settings to disk."""
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
