"""
Shared config and paths for ncclient (tray, CLI).
Settings are stored in settings.json. Config dir is standalone (no token path).
"""
import json
import os
import sys

__all__ = ["config_dir", "settings_path", "load_settings", "save_settings"]


def config_dir() -> str:
    """Base directory for settings and other config (e.g. nebula downloads)."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(appdata, "nebula-commander")
    return os.path.join(os.path.expanduser("~"), ".config", "nebula-commander")


def settings_path() -> str:
    """Path to settings.json (server, output_dir, interval, nebula_path)."""
    return os.path.join(config_dir(), "settings.json")


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
