"""
Windows auto-start at login via Registry Run key (HKCU).
"""
import os
import sys

if sys.platform != "win32":
    raise RuntimeError("autostart is Windows-only")

import winreg

_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "NebulaCommanderTray"


def is_autostart_enabled() -> bool:
    """Return True if the tray app is registered to run at login."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _REG_KEY,
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False


def enable_autostart(exe_path: str) -> bool:
    """Register the given executable to run at user login. Returns True on success."""
    exe_path = os.path.abspath(exe_path)
    if not os.path.isfile(exe_path):
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _REG_KEY,
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, exe_path)
            return True
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False


def disable_autostart() -> bool:
    """Remove the tray app from run-at-login. Returns True on success."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _REG_KEY,
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, _APP_NAME)
            return True
        except FileNotFoundError:
            return True  # already removed
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False
