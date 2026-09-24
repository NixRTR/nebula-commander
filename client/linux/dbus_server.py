"""
System D-Bus service (`org.beardedtek.NebulaCommander1`) hosted inside
the `ncclient run` process (client/ncclient.py's `cmd_run` starts this as a
daemon thread via `start()` below), replacing the old design where the
unprivileged Linux desktop app read/wrote files directly in a shared,
group-writable `/var/lib/ncclient/` directory. Every call is authorized
per-method via polkit's `CheckAuthorization` (`_check_authorized` below)
instead of Unix group membership - see
packaging/deb/service/payload/usr/share/polkit-1/actions/
org.beardedtek.NebulaCommander1.policy for the two actions this checks
(`...read`, `...manage`), both `allow_active=yes` (any active local
session is authorized - no group membership or relogin needed, unlike the
old design).

Uses jeepney (pure-Python, no GObject/GLib dependency - the same choice
already proven in client/linux/notify.py and confirmed here to freeze
cleanly via PyInstaller) rather than pydbus/dasbus, which would pull
PyGObject into this frozen CLI/service binary
(client/binaries/ncclient.spec) - exactly the dependency this project has
deliberately kept out of anything PyInstaller needs to freeze (see
client/linux/desktop.py's own module docstring for the fuller version of
this reasoning). The exact jeepney call shapes below (RequestName's flags/
reply, receive()'s TimeoutError, header field access via HeaderFields,
polkit's CheckAuthorization signature/subject shape) were verified against
a real jeepney 0.9.0 install and a real system bus + polkitd in a
throwaway Docker spike before writing this, not assumed from documentation.

Start/Stop/Restart of the systemd unit itself is deliberately NOT part of
this service - see client/linux/service_control.py, which talks to
systemd's own `org.freedesktop.systemd1` service directly instead, since
this service structurally can't answer "start" while it isn't running.

Best-effort by design: any failure standing this up (no system bus
reachable, another instance already owns the name) logs via the passed-in
`log` callback and disables the thread without ever raising into `cmd_run`
- the headless/NixOS/Docker deployment has no desktop consumer and often
no system bus at all, and must keep polling/running Nebula regardless.
"""
from __future__ import annotations

import json
import threading
from typing import Callable

import jeepney
import jeepney.bus_messages as bus_messages
import jeepney.io.blocking as blocking
from jeepney import HeaderFields

from client import service_api

__all__ = ["start", "BUS_NAME", "OBJECT_PATH", "INTERFACE"]

BUS_NAME = "org.beardedtek.NebulaCommander1"
OBJECT_PATH = "/org/beardedtek/NebulaCommander1"
INTERFACE = "org.beardedtek.NebulaCommander1"

ACTION_READ = "org.beardedtek.NebulaCommander1.read"
ACTION_MANAGE = "org.beardedtek.NebulaCommander1.manage"

# DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER - the only reply value meaning "we
# now own this name"; anything else (already owned elsewhere, queued, ...)
# means another instance is running or the bus policy is wrong.
_REPLY_PRIMARY_OWNER = 1

_AUTHORITY = jeepney.DBusAddress(
    "/org/freedesktop/PolicyKit1/Authority",
    bus_name="org.freedesktop.PolicyKit1",
    interface="org.freedesktop.PolicyKit1.Authority",
)


def _h_get_status(output_dir: str, msg) -> "tuple[str, tuple]":
    status = service_api.get_status(output_dir)
    return "sss", (status.get("state") or "", status.get("message") or "", status.get("updated_at") or "")


def _h_get_available_routes(output_dir: str, msg) -> "tuple[str, tuple]":
    routes = service_api.get_available_routes(output_dir)
    return "s", (json.dumps(routes),)


def _h_get_settings(output_dir: str, msg) -> "tuple[str, tuple]":
    return "s", (json.dumps(service_api.get_settings()),)


def _h_set_settings(output_dir: str, msg) -> "tuple[str, tuple]":
    (payload,) = msg.body
    service_api.set_settings(json.loads(payload))
    return "", ()


def _h_is_enrolled(output_dir: str, msg) -> "tuple[str, tuple]":
    enrolled, server = service_api.is_enrolled()
    return "bs", (enrolled, server)


def _h_enroll(output_dir: str, msg) -> "tuple[str, tuple]":
    server, code = msg.body
    node_id = service_api.enroll(server, code)
    return "s", (node_id or "",)


def _h_accept_route(output_dir: str, msg) -> "tuple[str, tuple]":
    cidr, via = msg.body
    service_api.accept_route(output_dir, cidr, via or None)
    return "", ()


def _h_reject_route(output_dir: str, msg) -> "tuple[str, tuple]":
    (cidr,) = msg.body
    service_api.reject_route(output_dir, cidr)
    return "", ()


def _h_accept_exit_node(output_dir: str, msg) -> "tuple[str, tuple]":
    (via,) = msg.body
    service_api.accept_exit_node(output_dir, via)
    return "", ()


def _h_reject_exit_node(output_dir: str, msg) -> "tuple[str, tuple]":
    service_api.reject_exit_node(output_dir)
    return "", ()


def _h_get_config_yaml(output_dir: str, msg) -> "tuple[str, tuple]":
    return "s", (service_api.get_config_yaml(output_dir),)


# member name -> (handler, required polkit action)
_METHODS = {
    "GetStatus": (_h_get_status, ACTION_READ),
    "GetAvailableRoutes": (_h_get_available_routes, ACTION_READ),
    "GetSettings": (_h_get_settings, ACTION_READ),
    "SetSettings": (_h_set_settings, ACTION_MANAGE),
    "IsEnrolled": (_h_is_enrolled, ACTION_READ),
    "Enroll": (_h_enroll, ACTION_MANAGE),
    "AcceptRoute": (_h_accept_route, ACTION_MANAGE),
    "RejectRoute": (_h_reject_route, ACTION_MANAGE),
    "AcceptExitNode": (_h_accept_exit_node, ACTION_MANAGE),
    "RejectExitNode": (_h_reject_exit_node, ACTION_MANAGE),
    "GetConfigYaml": (_h_get_config_yaml, ACTION_READ),
}


class _DBusServerThread(threading.Thread):
    def __init__(self, output_dir: str, stop_event: threading.Event, log: Callable[[str], None]) -> None:
        super().__init__(name="dbus-server", daemon=True)
        self._output_dir = output_dir
        self._stop_event = stop_event
        self._log = log
        self._conn = None
        self._authz_conn = None

    def run(self) -> None:
        try:
            self._conn = blocking.open_dbus_connection(bus="SYSTEM")
            self._authz_conn = blocking.open_dbus_connection(bus="SYSTEM")
        except Exception as e:
            self._log(f"D-Bus server disabled: could not connect to system bus: {e}")
            return

        try:
            proxy = blocking.Proxy(bus_messages.DBus(), self._conn)
            reply = proxy.RequestName(BUS_NAME, flags=bus_messages.DBusNameFlags.do_not_queue)
            if reply[0] != _REPLY_PRIMARY_OWNER:
                self._log(
                    f"D-Bus server disabled: could not own {BUS_NAME} "
                    f"(reply={reply[0]!r} - another instance already running?)"
                )
                self._close()
                return
        except Exception as e:
            self._log(f"D-Bus server disabled: RequestName failed: {e}")
            self._close()
            return

        self._log(f"D-Bus service ready: {BUS_NAME} at {OBJECT_PATH}")
        while not self._stop_event.is_set():
            try:
                msg = self._conn.receive(timeout=1.0)
            except TimeoutError:
                continue
            except Exception as e:
                self._log(f"D-Bus server: receive() failed, stopping: {e}")
                break
            try:
                self._dispatch(msg)
            except Exception as e:
                self._log(f"D-Bus server: unhandled dispatch error: {e}")
        self._close()

    def _close(self) -> None:
        for conn in (self._conn, self._authz_conn):
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass

    def _dispatch(self, msg) -> None:
        if msg.header.message_type != jeepney.MessageType.method_call:
            return
        f = msg.header.fields
        path = f.get(HeaderFields.path)
        interface = f.get(HeaderFields.interface)
        member = f.get(HeaderFields.member)
        sender = f.get(HeaderFields.sender)
        if path != OBJECT_PATH or interface != INTERFACE:
            return

        entry = _METHODS.get(member)
        if entry is None:
            self._conn.send(jeepney.new_error(msg, f"{INTERFACE}.Error.NoSuchMethod", "s", (f"No such method: {member}",)))
            return
        handler, action = entry

        if not self._check_authorized(sender, action):
            self._conn.send(jeepney.new_error(msg, f"{INTERFACE}.Error.NotAuthorized", "s", ("Not authorized.",)))
            return

        try:
            out_signature, body = handler(self._output_dir, msg)
        except service_api.ServiceApiError as e:
            self._conn.send(jeepney.new_error(msg, f"{INTERFACE}.Error.Failed", "s", (e.message,)))
            return
        except Exception as e:
            self._conn.send(jeepney.new_error(msg, f"{INTERFACE}.Error.Failed", "s", (str(e),)))
            return
        self._conn.send(jeepney.new_method_return(msg, out_signature, body))

    def _check_authorized(self, sender: "str | None", action: str) -> bool:
        if not sender:
            return False
        subject = ("system-bus-name", {"name": ("s", sender)})
        request = jeepney.new_method_call(
            _AUTHORITY,
            "CheckAuthorization",
            "(sa{sv})sa{ss}us",
            (subject, action, {}, 0, ""),
        )
        try:
            reply = self._authz_conn.send_and_get_reply(request, timeout=5)
        except Exception as e:
            self._log(f"D-Bus server: polkit CheckAuthorization failed: {e}")
            return False
        # send_and_get_reply() does NOT raise on an error-type reply (verified
        # against a real polkitd) - it returns the raw Message either way, so
        # this has to check message_type explicitly rather than relying on an
        # exception for the "polkit itself errored" case.
        if reply.header.message_type == jeepney.MessageType.error:
            self._log(f"D-Bus server: polkit CheckAuthorization error: {reply.body}")
            return False
        authorized, _is_challenge, _details = reply.body[0]
        return bool(authorized)


def start(output_dir: str, stop_event: threading.Event, log: Callable[[str], None]) -> threading.Thread:
    """Start the D-Bus server as a daemon thread and return it (join()able
    by the caller on shutdown). Never raises - failures are logged via
    `log` and leave the thread simply not serving anything."""
    thread = _DBusServerThread(output_dir, stop_event, log)
    thread.start()
    return thread
