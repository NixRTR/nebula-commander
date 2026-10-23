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
    "get_update_status",
    "set_auto_update",
    "check_for_updates_now",
    "list_networks",
    "enroll_network",
    "remove_network",
]

# Every per-network function below takes network=<id from list_networks()>. Without it
# (None) the call is the pre-0.8.0 one, which the service answers for its first network -
# that's also what keeps this app working against an older service.

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


def list_networks() -> "list[dict] | None":
    """Every enrolled network (id, name, server, tun_dev, overlay_ip, status, exit_node),
    [] when not enrolled, or None when the service can't be reached or predates 0.8.0
    (one network only - use the calls without network then)."""
    try:
        (payload,) = _call("ListNetworks")
    except DBusServiceError:
        return None
    return json.loads(payload)


def enroll_network(server: str, code: str) -> dict:
    """Enroll in another network. Returns {"id", "node_id", "name", "hostname"}."""
    (payload,) = _call("EnrollNetwork", "ss", (server, code), timeout=35)
    return json.loads(payload)


def remove_network(network: str) -> None:
    _call("RemoveNetwork", "s", (network,))


def _n(method: str, network: "str | None", signature: str = "", body: tuple = (), **kw) -> tuple:
    """Call method, or its *ForNetwork variant with the network id prepended."""
    if network is None:
        return _call(method, signature, body, **kw)
    return _call(f"{method}ForNetwork", "s" + signature, (network, *body), **kw)


def get_status(network: "str | None" = None) -> dict:
    """Returns the placeholder {"state": "unknown", ...} shape (matching
    client/status_store.py's own convention) if the service can't be
    reached at all, rather than raising - status display should always
    have something to show."""
    try:
        state, message, updated_at = _n("GetStatus", network)
    except DBusServiceError:
        return {"state": "unknown", "message": "Service not reachable", "updated_at": None}
    return {"state": state, "message": message, "updated_at": updated_at or None}


def get_available_routes(network: "str | None" = None) -> list:
    try:
        (payload,) = _n("GetAvailableRoutes", network)
    except DBusServiceError:
        return []
    return json.loads(payload)


def get_settings(network: "str | None" = None) -> dict:
    """Returns {} if the service can't be reached (matching the old
    load_settings()'s always-succeeds behavior on a missing/unreadable
    file) - callers (desktop.py's settings page, routes picker) never had
    to handle a read failure before and shouldn't have to now either."""
    try:
        (payload,) = _n("GetSettings", network)
    except DBusServiceError:
        return {}
    return json.loads(payload)


def set_settings(partial: dict) -> None:
    _call("SetSettings", "s", (json.dumps(partial),))


def get_update_status() -> dict:
    (payload,) = _call("GetUpdateStatus")
    return json.loads(payload)


def set_auto_update(enabled: bool, window_start: "str | None" = None, window_end: "str | None" = None) -> dict:
    (payload,) = _call("SetAutoUpdate", "bss", (enabled, window_start or "", window_end or ""), timeout=90)
    return json.loads(payload)


def check_for_updates_now() -> dict:
    (payload,) = _call("CheckForUpdatesNow", timeout=90)
    return json.loads(payload)


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


def accept_route(cidr: str, via: "str | None", network: "str | None" = None) -> None:
    _n("AcceptRoute", network, "ss", (cidr, via or ""))


def reject_route(cidr: str, network: "str | None" = None) -> None:
    _n("RejectRoute", network, "s", (cidr,))


def accept_exit_node(via: str, network: "str | None" = None) -> None:
    """A host has one exit node: one in use in another network is replaced."""
    _n("AcceptExitNode", network, "s", (via,))


def reject_exit_node(network: "str | None" = None) -> None:
    _n("RejectExitNode", network)


def get_config_yaml(network: "str | None" = None) -> str:
    (content,) = _n("GetConfigYaml", network)
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
