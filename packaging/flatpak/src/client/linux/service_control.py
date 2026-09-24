"""
Start/stop/restart/query the ncclient systemd service from the unprivileged
desktop app - via direct D-Bus calls to systemd's own
`org.freedesktop.systemd1.Manager`, not a `systemctl` subprocess. There is
no `systemctl` binary at all inside the Flatpak sandbox, so this works
identically in and out of it (the old design shelled out to `systemctl`
directly, or via `flatpak-spawn --host` inside the sandbox - see this
file's git history for that version). Authorized by the existing polkit
rule (packaging/deb/service/payload/usr/share/polkit-1/rules.d/
org.nixrtr.nebulacommander.rules), which grants any active local session
start/stop/restart on exactly the `ncclient.service` unit - polkit
resolves this from the D-Bus caller's real identity regardless of sandbox,
so no Flatpak-specific permission (like the old design's
`--talk-name=org.freedesktop.Flatpak`) is needed here at all.

`conn.send_and_get_reply()` does NOT raise on an error-type D-Bus reply -
verified against a real systemd1/dbus-daemon in this project's Docker
verification setup (only the higher-level jeepney `Proxy` wrapper does
that); every call here checks `reply.header.message_type` explicitly
instead of relying on an exception.
"""
from __future__ import annotations

import jeepney
import jeepney.io.blocking as blocking

__all__ = ["ServiceState", "get_state", "start", "stop", "restart"]

UNIT_NAME = "ncclient.service"

_MANAGER = jeepney.DBusAddress(
    "/org/freedesktop/systemd1",
    bus_name="org.freedesktop.systemd1",
    interface="org.freedesktop.systemd1.Manager",
)


class ServiceState:
    RUNNING = "running"
    STOPPED = "stopped"
    TRANSITIONING = "transitioning"
    NOT_INSTALLED = "not_installed"


def _connect() -> blocking.DBusConnection:
    return blocking.open_dbus_connection(bus="SYSTEM")


def get_state() -> str:
    """One of ServiceState.{RUNNING,STOPPED,TRANSITIONING,NOT_INSTALLED}."""
    try:
        conn = _connect()
    except Exception:
        return ServiceState.NOT_INSTALLED

    try:
        # LoadUnit (not GetUnit): GetUnit only returns units currently
        # loaded into systemd's live table, which does NOT include an
        # installed-but-currently-stopped unit with no pending jobs -
        # systemd unloads those from its live table, and GetUnit then
        # reports NoSuchUnit even though the unit *file* still exists on
        # disk (confirmed against a real systemd: a freshly-installed,
        # never-started unit already came back NoSuchUnit via GetUnit).
        # LoadUnit always succeeds with a synthetic object path for ANY
        # syntactically valid unit name, real or not - so "installed" has
        # to be read from that unit's own LoadState property instead (see
        # below), not from whether LoadUnit itself errors.
        msg = jeepney.new_method_call(_MANAGER, "LoadUnit", "s", (UNIT_NAME,))
        reply = conn.send_and_get_reply(msg, timeout=10)
        if reply.header.message_type == jeepney.MessageType.error:
            return ServiceState.NOT_INSTALLED
        (unit_path,) = reply.body

        props = jeepney.DBusAddress(
            unit_path, bus_name="org.freedesktop.systemd1", interface="org.freedesktop.DBus.Properties"
        )
        msg_load = jeepney.new_method_call(props, "Get", "ss", ("org.freedesktop.systemd1.Unit", "LoadState"))
        reply_load = conn.send_and_get_reply(msg_load, timeout=10)
        if reply_load.header.message_type == jeepney.MessageType.error:
            return ServiceState.NOT_INSTALLED
        (load_variant,) = reply_load.body
        if load_variant[1] != "loaded":
            # "not-found" (no unit file at all), "masked", "error", etc.
            return ServiceState.NOT_INSTALLED

        msg2 = jeepney.new_method_call(props, "Get", "ss", ("org.freedesktop.systemd1.Unit", "ActiveState"))
        reply2 = conn.send_and_get_reply(msg2, timeout=10)
        if reply2.header.message_type == jeepney.MessageType.error:
            return ServiceState.NOT_INSTALLED
        # A D-Bus variant unwraps to a (signature, value) tuple.
        (variant,) = reply2.body
        state = variant[1]
    except Exception:
        return ServiceState.NOT_INSTALLED
    finally:
        conn.close()

    if state == "active":
        return ServiceState.RUNNING
    if state in ("activating", "deactivating", "reloading"):
        return ServiceState.TRANSITIONING
    if state in ("inactive", "failed"):
        return ServiceState.STOPPED
    return ServiceState.NOT_INSTALLED


def _job_action(method: str) -> "tuple[bool, str]":
    """Returns (ok, message). message is the D-Bus error detail on failure,
    empty on success."""
    try:
        conn = _connect()
    except Exception as e:
        return False, str(e)
    try:
        msg = jeepney.new_method_call(_MANAGER, method, "ss", (UNIT_NAME, "replace"))
        reply = conn.send_and_get_reply(msg, timeout=15)
        if reply.header.message_type == jeepney.MessageType.error:
            detail = reply.body[0] if reply.body else f"{method} failed"
            return False, str(detail)
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()
    return True, ""


def start() -> "tuple[bool, str]":
    return _job_action("StartUnit")


def stop() -> "tuple[bool, str]":
    return _job_action("StopUnit")


def restart() -> "tuple[bool, str]":
    return _job_action("RestartUnit")
