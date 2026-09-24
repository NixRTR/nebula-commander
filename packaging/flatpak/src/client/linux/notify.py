"""
Transient desktop notifications for state changes (connected/disconnected/
error, a new route becomes available, DNS applied). No persistent indicator
of any kind - see client/linux/desktop.py's module docstring for why (GNOME
Shell has no tray icon support at all as of GNOME Shell 50; notifications,
unlike tray icons, were never removed and work out of the box everywhere).

Two backends, tried in order, both best-effort (a failure here should never
break the caller - a missed notification is not worth crashing the desktop
app or the service over):

1. A direct call to org.freedesktop.Notifications.Notify on the session bus
   via `jeepney` (pure-Python, no GObject/libdbus binding - freezes cleanly
   with PyInstaller, unlike PyGObject).
2. `notify-send` (part of libnotify, present on virtually every desktop
   Linux install - Debian/Ubuntu/Fedora/openSUSE all ship it in their
   default desktop task/pattern) via subprocess, if jeepney is unavailable
   or the session bus call fails for any reason (e.g. running under sudo
   with no DBUS_SESSION_BUS_ADDRESS).

Deliberately no action-button support: that needs an event loop listening
for ActionInvoked signals, which is a meaningfully bigger piece of plumbing
for a "nudge the user to open the app" notification. Anything requiring
real interaction (enroll, settings, accept/reject a route) happens in the
app window (desktop.py), not in the notification itself.
"""
from __future__ import annotations

import shutil
import subprocess

__all__ = ["notify"]

_APP_NAME = "Nebula Commander"
# Fixed id so each call replaces the previous notification instead of piling
# up a new banner per state change - matches how the Windows app's single
# tray balloon/tooltip behaves.
_REPLACES_ID = 0

_URGENCY_LEVELS = {"low": 0, "normal": 1, "critical": 2}


def _notify_via_dbus(summary: str, body: str, urgency: str, timeout_ms: int) -> bool:
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
    except ImportError:
        return False

    notifications = DBusAddress(
        "/org/freedesktop/Notifications",
        bus_name="org.freedesktop.Notifications",
        interface="org.freedesktop.Notifications",
    )
    hints = {"urgency": ("y", _URGENCY_LEVELS.get(urgency, 1))}
    msg = new_method_call(
        notifications,
        "Notify",
        "susssasa{sv}i",
        (_APP_NAME, _REPLACES_ID, "", summary, body, [], hints, timeout_ms),
    )
    try:
        conn = open_dbus_connection(bus="SESSION")
        try:
            conn.send_and_get_reply(msg, timeout=5)
        finally:
            conn.close()
        return True
    except Exception:
        return False


def _notify_via_notify_send(summary: str, body: str, urgency: str, timeout_ms: int) -> bool:
    exe = shutil.which("notify-send")
    if not exe:
        return False
    try:
        subprocess.run(
            [
                exe,
                "--app-name", _APP_NAME,
                "--urgency", urgency if urgency in _URGENCY_LEVELS else "normal",
                "--expire-time", str(timeout_ms),
                summary,
                body,
            ],
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def notify(summary: str, body: str = "", urgency: str = "normal", timeout_ms: int = 5000) -> None:
    """Best-effort: fire a transient desktop notification. Never raises."""
    if _notify_via_dbus(summary, body, urgency, timeout_ms):
        return
    _notify_via_notify_send(summary, body, urgency, timeout_ms)
