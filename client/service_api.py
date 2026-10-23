"""
Pure business-logic core for enroll/settings/route-accept operations - no
`sys.exit`/`print`, unlike client/ncclient.py's CLI-shaped `cmd_*` functions.

Extracted so both the CLI (client/ncclient.py's `cmd_enroll`/`cmd_routes_*`,
now thin wrappers that catch the exceptions here and print+exit(1), keeping
today's exact CLI behavior) and the Linux D-Bus server
(client/linux/dbus_server.py's method handlers, which translate these
exceptions into D-Bus error replies instead) share one implementation
rather than two independently-maintained copies.

`enroll()` does the HTTP call and `token_store.set_token()` itself, in
whichever process calls it - when called from the D-Bus server (running
inside the privileged `ncclient run` process), the device token never
leaves that process, unlike the old design where an unprivileged desktop
app made the HTTP call itself and wrote the token into a group-readable
file directly.

`_lock` guards every settings.json/token read-modify-write sequence below.
Harmless across separate CLI invocations (one lock per short-lived
process); load-bearing once client/linux/dbus_server.py's handler thread
and client/ncclient.py's poll-loop thread can both touch settings.json
within the same long-running `ncclient run` process.

Since 0.8.0 one ncclient can be enrolled in several networks (client/config.py).
Every per-network function takes `network` - an enrollment id or name. None means
the only enrollment; with several, `first_if_many` callers (the pre-0.8.0 D-Bus/pipe
methods an older app still calls) get the first one and everyone else gets a
ServiceApiError asking which network. `output_dir` is always the base directory; each
network's files are in config.enrollment_dir(output_dir, id).
"""
from __future__ import annotations

import ipaddress
import json
import os
import sys
import threading

from client.config import (
    enrollment_dir,
    enrollment_view,
    enrollments,
    find_enrollment,
    load_settings,
    new_enrollment_id,
    save_settings,
)
from client.token_store import delete_token, get_token, set_token

__all__ = [
    "ServiceApiError",
    "EnrollError",
    "list_networks",
    "remove_network",
    "resolve_network",
    "network_dir",
    "RouteError",
    "enroll",
    "is_enrolled",
    "get_settings",
    "set_settings",
    "get_status",
    "get_advertised_routes",
    "get_available_routes",
    "redact_config_yaml",
    "get_config_yaml",
    "validate_new_subnet_route",
    "accept_route",
    "reject_route",
    "accept_exit_node",
    "reject_exit_node",
    "UpdateSettingsError",
    "get_update_status",
    "set_auto_update",
    "check_updates_now",
]

_lock = threading.Lock()

# Bumped by in-process callers (the D-Bus server, the Windows pipe server) after a
# route/settings change so every network's run_poll_loop applies it now instead of on
# its next poll. A counter rather than an Event: with several networks each loop must
# see the request, not just the first to look.
_poll_now_generation = 0
_poll_now_lock = threading.Lock()


def request_poll_now() -> None:
    global _poll_now_generation
    with _poll_now_lock:
        _poll_now_generation += 1


def poll_now_generation() -> int:
    """Compare with an earlier value: different means a poll was requested since."""
    return _poll_now_generation


def take_poll_now(seen: "list[int] | None" = None) -> bool:
    """True (once per caller) if a poll was requested since the caller last looked.
    seen: a one-element list holding the caller's last generation (updated here); the
    default is a module-wide slot, the pre-0.8.0 single-loop behaviour."""
    slot = seen if seen is not None else _default_seen
    current = _poll_now_generation
    if current != slot[0]:
        slot[0] = current
        return True
    return False


_default_seen = [0]

# Keys a caller (CLI flag or D-Bus SetSettings) may set directly.
# accepted_subnet_routes/accepted_exit_node/node_id are only ever mutated by
# this module's own accept/reject/enroll functions, never by a raw
# SetSettings call - keeps route selection consistent with what
# available-routes.json actually currently offers.
#
# nebula_path is deliberately NOT settable: on Windows the LocalSystem
# service used to execute whatever path settings.json named, which let any
# caller who could write settings run arbitrary code as SYSTEM. The Windows
# service now only ever runs its own verified install (see
# client/windows/nebula_install.py), and Linux never read it from
# settings.json in the first place.
_SETTABLE_KEYS = ("server", "interval", "accept_dns", "exit_allow_lan")
_BOOL_KEYS = ("accept_dns", "exit_allow_lan")


class ServiceApiError(Exception):
    """Base class; .message is the user-facing text (printed by the CLI
    wrapper, or carried in a D-Bus error reply's body by the server)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class EnrollError(ServiceApiError):
    pass


class UpdateSettingsError(ServiceApiError):
    pass


class RouteError(ServiceApiError):
    pass


def _server_url(server: str) -> str:
    base = server.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    return base


def resolve_network(network: "str | None", first_if_many: bool = False) -> dict:
    """The enrollment `network` (id or name) refers to. Raises ServiceApiError when there
    is none, or when network is None with several enrolled (unless first_if_many)."""
    settings = load_settings()
    items = enrollments(settings)
    if not items:
        raise ServiceApiError("Not enrolled in any network yet.")
    if network is None and first_if_many:
        return items[0]
    found = find_enrollment(settings, network)
    if found is None:
        if network is None:
            names = ", ".join(e.get("name") or e["id"] for e in items)
            raise ServiceApiError(f"Enrolled in several networks ({names}) - say which one.")
        raise ServiceApiError(f"No enrolled network {network!r}.")
    return found


def network_dir(output_dir: str, network: "str | None", first_if_many: bool = False) -> str:
    return enrollment_dir(output_dir, resolve_network(network, first_if_many)["id"])


def list_networks(output_dir: str) -> list[dict]:
    """Every enrolled network with what an app shows on its card. Never includes a token."""
    from client.status_store import load_status

    settings = load_settings()
    exit_node = settings.get("exit_node") if isinstance(settings.get("exit_node"), dict) else None
    out = []
    for e in enrollments(settings):
        d = enrollment_dir(output_dir, e["id"])
        tun_dev = _tun_dev(d)
        status = load_status(os.path.join(d, "status.json"))
        out.append({
            "id": e["id"],
            "name": e.get("name") or "",
            "hostname": e.get("hostname") or "",
            "server": e.get("server") or "",
            "node_id": e.get("node_id"),
            "tun_dev": tun_dev or "",
            # Windows: recorded by the service (a PowerShell call per network is too slow here).
            "overlay_ip": (status.get("overlay_ip") if sys.platform == "win32" else _overlay_ip(tun_dev)) or "",
            "status": {k: status.get(k) for k in ("state", "message", "updated_at")},
            "exit_node": (exit_node or {}).get("via") if (exit_node or {}).get("enrollment") == e["id"] else None,
            "accepted_subnet_routes": e.get("accepted_subnet_routes") or [],
        })
    return out


def _tun_dev(state_dir: str) -> "str | None":
    try:
        import yaml
        with open(os.path.join(state_dir, "config.yaml"), "r", encoding="utf-8") as f:
            dev = ((yaml.safe_load(f) or {}).get("tun") or {}).get("dev")
        return dev if isinstance(dev, str) and dev else None
    except Exception:
        return None


def _overlay_ip(tun_dev: "str | None") -> "str | None":
    if not tun_dev:
        return None
    try:
        from client.connectivity import interface_ipv4
        return interface_ipv4(tun_dev)
    except Exception:
        return None


def remove_network(output_dir: str, network: str) -> str:
    """Forget an enrolled network: its settings entry, token, and the host's exit node if
    it was this network's. The running service stops that network's Nebula, removes its
    DNS/routing and deletes its directory (client/supervisor.py); without a service the
    directory is removed on the next start. Returns the removed id."""
    with _lock:
        settings = load_settings()
        e = find_enrollment(settings, network)
        if e is None:
            raise ServiceApiError(f"No enrolled network {network!r}.")
        settings["enrollments"] = [x for x in enrollments(settings) if x["id"] != e["id"]]
        if isinstance(settings.get("exit_node"), dict) and settings["exit_node"].get("enrollment") == e["id"]:
            settings["exit_node"] = None
        save_settings(settings)
        delete_token(e["id"])
    return e["id"]


def enroll(server: str, code: str) -> "str | None":
    """Enroll this device in a network with a one-time code. Adds a network, or replaces
    the token of one already enrolled as the same node on the same server (re-enroll).
    Returns node_id (may be None). Raises EnrollError on any failure. The HTTP call and
    token write both happen here, in the caller's process - see module docstring."""
    return enroll_network(server, code)["node_id"]


def enroll_network(server: str, code: str) -> dict:
    """enroll(), returning {"id", "node_id", "name", "hostname"} of the enrollment."""
    import requests

    base = _server_url(server)
    url = f"{base}/api/device/enroll"
    code = code.strip().upper()
    try:
        r = requests.post(url, json={"code": code}, timeout=30)
    except requests.RequestException as e:
        raise EnrollError(f"Enroll request failed: {e}") from e
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise EnrollError(f"Enroll failed: {detail}")
    data = r.json()
    token = data["device_token"]
    node_id = data.get("node_id")
    with _lock:
        settings = load_settings()
        items = enrollments(settings)
        e = next((x for x in items if x.get("server") == base and node_id is not None and x.get("node_id") == node_id), None)
        if e is None:
            e = {"id": new_enrollment_id(), "server": base, "node_id": node_id, "accepted_subnet_routes": []}
            items.append(e)
        if data.get("network_name"):
            e["name"] = data["network_name"]
        if data.get("hostname"):
            e["hostname"] = data["hostname"]
        set_token(token, e["id"])
        settings["enrollments"] = items
        save_settings(settings)
    return {"id": e["id"], "node_id": node_id, "name": e.get("name") or "", "hostname": e.get("hostname") or ""}


def is_enrolled() -> "tuple[bool, str]":
    """(enrolled, server of the first network) - never returns the token itself."""
    items = enrollments(load_settings())
    for e in items:
        if get_token(e["id"]) is not None:
            return True, (e.get("server") or "").strip()
    return False, (items[0].get("server") or "").strip() if items else ""


def get_settings(network: "str | None" = None) -> dict:
    """One network's view of settings.json (host-wide keys plus its server, node_id,
    accepted routes and accepted_exit_node - the pre-0.8.0 shape apps read), or just
    the host-wide keys when nothing is enrolled. Never includes a token."""
    settings = load_settings()
    if not enrollments(settings):
        return {k: v for k, v in settings.items() if k not in ("enrollments", "exit_node")}
    return enrollment_view(settings, resolve_network(network, first_if_many=True)["id"])


def set_settings(partial: dict, network: "str | None" = None) -> None:
    """Merge interval/accept_dns/exit_allow_lan (host-wide) and server (one network's)
    into settings.json. Silently ignores any other key (route selection/node_id have
    their own dedicated functions below - never settable via a raw partial update).
    exit_allow_lan: while an exit node is in use, keep local-network traffic direct
    (default) - see client/exit_routing.py."""
    updates = {k: v for k, v in partial.items() if k in _SETTABLE_KEYS}
    for k in _BOOL_KEYS:
        if k in updates and not isinstance(updates[k], bool):
            raise ServiceApiError(f"{k} must be true or false.")
    with _lock:
        settings = load_settings()
        server = updates.pop("server", None)
        if server is not None and enrollments(settings):
            target = resolve_network(network, first_if_many=True)["id"]
            for e in enrollments(settings):
                if e["id"] == target:
                    e["server"] = _server_url(server) if server.strip() else e.get("server")
        elif server is not None:
            settings["server"] = server  # before any enrollment: the default for the first enroll
        save_settings({**settings, **updates})


def get_advertised_routes(network: "str | None" = None, first_if_many: bool = True) -> list[str]:
    """CIDRs this device advertises as a subnet router / exit node in a network,
    fetched with the stored token inside the caller's (privileged) process - so a GUI
    can show them without ever reading the token itself. Empty when not enrolled or
    on any failure."""
    from client.ncclient import _fetch_advertised_routes

    try:
        e = resolve_network(network, first_if_many)
    except ServiceApiError:
        return []
    token = get_token(e["id"])
    server = (e.get("server") or "").strip()
    if not token or not server:
        return []
    return _fetch_advertised_routes(_server_url(server), token)


def get_status(output_dir: str, network: "str | None" = None, first_if_many: bool = True) -> dict:
    from client.status_store import load_status

    try:
        d = network_dir(output_dir, network, first_if_many)
    except ServiceApiError as e:
        return {"state": "idle", "message": e.message, "updated_at": None}
    return load_status(os.path.join(d, "status.json"))


def _available_routes_path(output_dir: str) -> str:
    return os.path.join(output_dir, "available-routes.json")


def get_available_routes(output_dir: str, network: "str | None" = None, first_if_many: bool = True) -> list[dict]:
    """Everything currently offered to this node in a network. Empty list if
    available-routes.json doesn't exist yet (no successful poll since the
    service last started), can't be read, or nothing is enrolled."""
    try:
        path = _available_routes_path(network_dir(output_dir, network, first_if_many))
    except ServiceApiError:
        return []
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


REDACTED = "<redacted>"


def redact_config_yaml(content: str) -> str:
    """Replace pki.key (the node's inline private key, see the backend's
    config_generator) with a placeholder. Readers of this API are allowed to
    see the config (read action / unprivileged pipe client) but must never
    get the node's identity. Falls back to dropping every PEM private-key
    block if the YAML can't be parsed, so a malformed file still never
    leaks the key."""
    import re

    import yaml

    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError:
        parsed = None
    if isinstance(parsed, dict):
        pki = parsed.get("pki")
        if isinstance(pki, dict) and "key" in pki:
            pki["key"] = REDACTED
        return yaml.safe_dump(parsed, default_flow_style=False, sort_keys=False)
    return re.sub(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        REDACTED,
        content,
        flags=re.DOTALL,
    )


def get_config_yaml(output_dir: str, network: "str | None" = None, first_if_many: bool = True) -> str:
    """A network's config.yaml with the private key redacted - see redact_config_yaml."""
    path = os.path.join(network_dir(output_dir, network, first_if_many), "config.yaml")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return redact_config_yaml(f.read())
    except OSError as e:
        raise ServiceApiError(f"Could not read {path}: {e}") from e


def validate_new_subnet_route(new_route: str, currently_accepted: "list[dict] | None") -> "str | None":
    """Returns an error message if accepting new_route would overlap an
    already-accepted subnet route's CIDR, else None. Exit-node CIDRs are
    never part of this check - accepting an exit node doesn't conflict with
    also accepting subnet routes (Nebula's longest-prefix-match naturally
    prefers the specific subnet over the exit node's 0.0.0.0/0 catch-all
    anyway)."""
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


def _update_enrollment(settings: dict, enrollment_id: str, **fields) -> None:
    for e in enrollments(settings):
        if e["id"] == enrollment_id:
            e.update(fields)


def accept_route(
    output_dir: str, cidr: str, via: "str | None", network: "str | None" = None, first_if_many: bool = False
) -> "tuple[str, str]":
    """Accept an offered subnet route in a network. Returns (cidr, via) actually
    accepted. Raises RouteError if not offered, ambiguous, an exit-node
    CIDR, or it would overlap an already-accepted route."""
    e = resolve_network(network, first_if_many)
    available = get_available_routes(output_dir, e["id"])
    matches = [r for r in available if r.get("route") == cidr and (via is None or r.get("via") == via)]
    if not matches:
        raise RouteError(f"{cidr!r} is not currently offered to this node.")
    if len(matches) > 1:
        vias = ", ".join(sorted({m.get("via") or "" for m in matches}))
        raise RouteError(f"{cidr!r} is offered by multiple gateways ({vias}) - specify via.")
    match = matches[0]
    if match.get("kind") == "exit":
        raise RouteError(f"{cidr!r} is an exit-node route - use accept_exit_node instead.")

    with _lock:
        settings = load_settings()
        current = find_enrollment(settings, e["id"]) or {}
        accepted_subnet_routes = current.get("accepted_subnet_routes") or []
        error = validate_new_subnet_route(cidr, accepted_subnet_routes)
        if error:
            raise RouteError(error)
        accepted_subnet_routes = [r for r in accepted_subnet_routes if r.get("route") != cidr] + [
            {"route": cidr, "via": match.get("via")}
        ]
        _update_enrollment(settings, e["id"], accepted_subnet_routes=accepted_subnet_routes)
        save_settings(settings)
    return cidr, match.get("via")


def reject_route(output_dir: str, cidr: str, network: "str | None" = None, first_if_many: bool = False) -> None:
    e = resolve_network(network, first_if_many)
    with _lock:
        settings = load_settings()
        accepted_subnet_routes = (find_enrollment(settings, e["id"]) or {}).get("accepted_subnet_routes") or []
        remaining = [r for r in accepted_subnet_routes if r.get("route") != cidr]
        if len(remaining) == len(accepted_subnet_routes):
            raise RouteError(f"{cidr!r} was not accepted.")
        _update_enrollment(settings, e["id"], accepted_subnet_routes=remaining)
        save_settings(settings)


def accept_exit_node(output_dir: str, via: str, network: "str | None" = None, first_if_many: bool = False) -> None:
    """Route all of this host's traffic through an exit node of a network. A host has
    one exit node: one already in use in another network is replaced."""
    e = resolve_network(network, first_if_many)
    available = get_available_routes(output_dir, e["id"])
    if not any(r.get("kind") == "exit" and r.get("via") == via for r in available):
        raise RouteError(f"No exit node with via={via!r} is currently offered to this node.")
    with _lock:
        settings = load_settings()
        settings["exit_node"] = {"enrollment": e["id"], "via": via}
        save_settings(settings)


def reject_exit_node(output_dir: str, network: "str | None" = None, first_if_many: bool = False) -> None:
    """Stop using the host's exit node. With network set, only if it belongs to that
    network."""
    with _lock:
        settings = load_settings()
        current = settings.get("exit_node") if isinstance(settings.get("exit_node"), dict) else None
        if not current or not current.get("via"):
            raise RouteError("No exit node is currently accepted.")
        if network is not None or not first_if_many:
            try:
                e = resolve_network(network, first_if_many)
            except ServiceApiError:
                e = None
            if network is not None and (e is None or current.get("enrollment") != e["id"]):
                raise RouteError("This network's exit node isn't the one in use.")
        settings["exit_node"] = None
        save_settings(settings)


# --- automatic updates (client/updates.py) -------------------------------------------
# Deliberately not in _SETTABLE_KEYS: like routes, auto_update has its own functions,
# which validate the window and (on deb/rpm installs) arm the systemd timer.

def get_update_status() -> dict:
    from client import updates
    from client.version import VERSION, is_dev_build

    kind = updates.install_kind()
    settings = updates.auto_update_settings()
    status = updates.load_status()
    return {
        **status,
        "installed_version": VERSION,
        "dev_build": is_dev_build(),
        "install_kind": kind,
        "supported": kind in updates.SUPPORTED_KINDS,
        "mode": updates.mode(kind=kind),
        **settings,
    }


def set_auto_update(enabled: bool, window_start: "str | None" = None, window_end: "str | None" = None) -> dict:
    """Turn automatic updates on/off and/or change the window. Returns the new status."""
    from client import updates

    kind = updates.install_kind()
    current = updates.auto_update_settings()
    try:
        new = updates.validate_settings(
            enabled, window_start or current["window_start"], window_end or current["window_end"],
        )
        if enabled and kind not in updates.SUPPORTED_KINDS:
            raise updates.UpdateError(
                "Automatic updates aren't available for this kind of install (they cover the "
                "Windows installer, deb/rpm packages from the official repository, and NixOS). "
                "Docker images, Flatpak and pip installs are updated the way they were installed."
            )
        with _lock:
            if kind == "package":
                from client.linux import auto_update

                auto_update.apply(new["enabled"], new["window_start"], new["window_end"])
            save_settings({**load_settings(), updates.SETTINGS_KEY: new})
    except updates.UpdateError as e:
        raise UpdateSettingsError(str(e)) from e
    return get_update_status()


def check_updates_now() -> dict:
    """Check the signed manifest now (never installs by itself). On a deb/rpm install
    with automatic updates on, an available update is then installed right away by
    ncclient-update.service. The Windows service does its own install step instead
    (client/windows/updater.py)."""
    from client import updates

    kind = updates.install_kind()
    result = updates.check(kind)
    result.pop("manifest", None)
    if kind == "package" and updates.mode(kind=kind) == "install" and result.get("available_version"):
        from client.linux import auto_update

        try:
            auto_update.run_now()
            result["install_started"] = True
        except updates.UpdateError as e:
            raise UpdateSettingsError(str(e)) from e
    return {**get_update_status(), **result}
