"""
Linux auto-start at login via an XDG autostart .desktop file
(~/.config/autostart/), the standard mechanism honored by GNOME, KDE, XFCE,
Cinnamon, MATE and friends alike - the closest cross-desktop equivalent to
the Windows HKCU Run key (see client/windows-app/Services/AutoStart.cs).
"""
from __future__ import annotations

import os

_APP_ID = "org.beardedtek.NebulaCommander"


def _autostart_dir() -> str:
    xdg_config = os.environ.get("XDG_CONFIG_HOME", "").strip() or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(xdg_config, "autostart")


def _desktop_file_path() -> str:
    return os.path.join(_autostart_dir(), f"{_APP_ID}.desktop")


def is_autostart_enabled() -> bool:
    return os.path.isfile(_desktop_file_path())


def enable_autostart(exec_path: str) -> bool:
    """Write an autostart .desktop file launching exec_path. Returns True on success."""
    exec_path = os.path.abspath(exec_path)
    if not os.path.isfile(exec_path):
        return False
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Nebula Commander\n"
        f"Exec={exec_path}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    try:
        os.makedirs(_autostart_dir(), exist_ok=True)
        with open(_desktop_file_path(), "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except OSError:
        return False


def disable_autostart() -> bool:
    try:
        os.remove(_desktop_file_path())
        return True
    except FileNotFoundError:
        return True  # already removed
    except OSError:
        return False
