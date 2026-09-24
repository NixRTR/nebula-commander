"""
Client for the system D-Bus service client/linux/dbus_server.py exposes
from inside the privileged `ncclient run` process - used by
client/linux/desktop.py in place of the old design's direct file access to
/var/lib/ncclient/*. See dbus_server.py's module docstring for the full
rationale (Flathub permission minimization, dropping the
nebula-commander-group/relogin requirement, keeping the enrollment token
out of the unprivileged desktop process entirely).

Every call here can raise DBusServiceError - the service isn't reachable
(not running/installed, or - if nothing owns the well-known name - D-Bus's
own activation-lookup failure, which surfaces the same way), the caller
isn't authorized, or the service reported a Failed error. desktop.py checks
client.linux.service_control.get_state() before most calls anyway (mirrors
the old design's own pattern), so the "service not running" case is
normally already handled before it would ever reach here.
"""
from __future__ import annotations

import ipaddress
import json

import jeepney
import jeepney.io.blocking as blocking

__all__ = [
    "DBusServiceError",
    "get_status",
    "get_available_routes",
    "get_settings",
    "set_settings",
    "is_enrolled",
    "enroll",
    "accept_route",
    "reject_route",
    "accept_exit_node",
    "reject_exit_node",
    "get_config_yaml",
    "validate_new_subnet_route",
]

BUS_NAME = "org.beardedtek.NebulaCommander1"
OBJECT_PATH = "/org/beardedtek/NebulaCommander1"
INTERFACE = "org.beardedtek.NebulaCommander1"

_ADDRESS = jeepney.DBusAddress(OBJECT_PATH, bus_name=BUS_NAME, interface=INTERFACE)


class DBusServiceError(Exception):
    """.message is the user-facing text."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _call(method: str, signature: str = "", body: tuple = (), timeout: float = 10.0) -> tuple:
    try:
        conn = blocking.open_dbus_connection(bus="SYSTEM")
    except Exception as e:
        raise DBusServiceError(f"Could not connect to the system bus: {e}") from e
    try:
        msg = jeepney.new_method_call(_ADDRESS, method, signature, body)
        try:
            reply = conn.send_and_get_reply(msg, timeout=timeout)
        except Exception as e:
            raise DBusServiceError(f"{method} failed: {e}") from e
        # conn.send_and_get_reply() does NOT raise on an error-type reply
        # the way the higher-level Proxy wrapper does (verified against a
        # real system bus) - it just hands back the raw Message, so an
        # error reply has to be detected explicitly via message_type.
        if reply.header.message_type == jeepney.MessageType.error:
            detail = reply.body[0] if reply.body else "Unknown D-Bus error"
            raise DBusServiceError(str(detail))
        return reply.body
    finally:
        conn.close()


def get_status() -> dict:
    """Returns the placeholder {"state": "unknown", ...} shape (matching
    client/status_store.py's own convention) if the service can't be
    reached at all, rather than raising - status display should always
    have something to show."""
    try:
        state, message, updated_at = _call("GetStatus")
    except DBusServiceError:
        return {"state": "unknown", "message": "Service not reachable", "updated_at": None}
    return {"state": state, "message": message, "updated_at": updated_at or None}


def get_available_routes() -> list:
    try:
        (payload,) = _call("GetAvailableRoutes")
    except DBusServiceError:
        return []
    return json.loads(payload)


def get_settings() -> dict:
    """Returns {} if the service can't be reached (matching the old
    load_settings()'s always-succeeds behavior on a missing/unreadable
    file) - callers (desktop.py's settings page, routes picker) never had
    to handle a read failure before and shouldn't have to now either."""
    try:
        (payload,) = _call("GetSettings")
    except DBusServiceError:
        return {}
    return json.loads(payload)


def set_settings(partial: dict) -> None:
    _call("SetSettings", "s", (json.dumps(partial),))


def is_enrolled() -> "tuple[bool, str]":
    """(False, "") if the service can't be reached - a safe display
    default, not a claim that the device is actually unenrolled."""
    try:
        enrolled, server = _call("IsEnrolled")
    except DBusServiceError:
        return False, ""
    return enrolled, server


def enroll(server: str, code: str) -> str:
    (node_id,) = _call("Enroll", "ss", (server, code), timeout=35)
    return node_id


def accept_route(cidr: str, via: "str | None") -> None:
    _call("AcceptRoute", "ss", (cidr, via or ""))


def reject_route(cidr: str) -> None:
    _call("RejectRoute", "s", (cidr,))


def accept_exit_node(via: str) -> None:
    _call("AcceptExitNode", "s", (via,))


def reject_exit_node() -> None:
    _call("RejectExitNode")


def get_config_yaml() -> str:
    (content,) = _call("GetConfigYaml")
    return content


def validate_new_subnet_route(new_route: str, currently_accepted: "list[dict] | None") -> "str | None":
    """Standalone copy of client/service_api.py's pure CIDR-overlap check -
    used for instant UI feedback as the user toggles a route switch, before
    even calling accept_route(). Deliberately duplicated rather than
    imported from client.service_api (which pulls in requests/PyYAML via
    client.ncclient, a dependency chain this desktop app otherwise has no
    reason to carry - see packaging/deb/build.py's _LINUX_SOURCE_FILES)."""
    try:
        new_net = ipaddress.ip_network(new_route, strict=False)
    except ValueError as e:
        return f"Invalid CIDR {new_route!r}: {e}"
    for r in currently_accepted or []:
        existing_route = r.get("route")
        try:
            existing_net = ipaddress.ip_network(existing_route, strict=False)
        except (ValueError, TypeError):
            continue
        if new_net.overlaps(existing_net):
            return f"{new_route} overlaps already-accepted {existing_route} (via {r.get('via')})"
    return None
