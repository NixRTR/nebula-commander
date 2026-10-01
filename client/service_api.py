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
"""
from __future__ import annotations

import ipaddress
import json
import os
import threading

from client.config import load_settings, save_settings
from client.token_store import get_token, set_token

__all__ = [
    "ServiceApiError",
    "EnrollError",
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
_SETTABLE_KEYS = ("server", "interval", "accept_dns")


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


def enroll(server: str, code: str) -> "str | None":
    """Enroll this device with a one-time code. Returns node_id (may be
    None). Raises EnrollError on any failure. The HTTP call and token write
    both happen here, in the caller's process - see module docstring."""
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
        set_token(token)
        save_settings({**load_settings(), "server": base, "node_id": node_id})
    return node_id


def is_enrolled() -> "tuple[bool, str]":
    """(enrolled, server) - never returns the token itself."""
    enrolled = get_token() is not None
    server = (load_settings().get("server") or "").strip()
    return enrolled, server


def get_settings() -> dict:
    """settings.json's content, as-is (never includes the token - that's
    always stored separately via client.token_store)."""
    return load_settings()


def set_settings(partial: dict) -> None:
    """Merge server/interval/accept_dns into settings.json.
    Silently ignores any other key (route selection/node_id have their own
    dedicated functions below - never settable via a raw partial update)."""
    updates = {k: v for k, v in partial.items() if k in _SETTABLE_KEYS}
    with _lock:
        save_settings({**load_settings(), **updates})


def get_advertised_routes() -> list[str]:
    """CIDRs this device advertises as a subnet router / exit node, fetched
    with the stored token inside the caller's (privileged) process - so a GUI
    can show them without ever reading the token itself. Empty when not
    enrolled or on any failure."""
    from client.ncclient import _fetch_advertised_routes

    token = get_token()
    server = (load_settings().get("server") or "").strip()
    if not token or not server:
        return []
    return _fetch_advertised_routes(_server_url(server), token)


def get_status(output_dir: str) -> dict:
    from client.status_store import load_status

    return load_status(os.path.join(output_dir, "status.json"))


def _available_routes_path(output_dir: str) -> str:
    return os.path.join(output_dir, "available-routes.json")


def get_available_routes(output_dir: str) -> list[dict]:
    """Everything currently offered to this node. Empty list if
    available-routes.json doesn't exist yet (no successful poll since the
    service last started) or can't be read."""
    path = _available_routes_path(output_dir)
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


def get_config_yaml(output_dir: str) -> str:
    """config.yaml with the private key redacted - see redact_config_yaml."""
    path = os.path.join(output_dir, "config.yaml")
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


def accept_route(output_dir: str, cidr: str, via: "str | None") -> "tuple[str, str]":
    """Accept an offered subnet route. Returns (cidr, via) actually
    accepted. Raises RouteError if not offered, ambiguous, an exit-node
    CIDR, or it would overlap an already-accepted route."""
    available = get_available_routes(output_dir)
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
        accepted_subnet_routes = settings.get("accepted_subnet_routes") or []
        error = validate_new_subnet_route(cidr, accepted_subnet_routes)
        if error:
            raise RouteError(error)
        accepted_subnet_routes = [r for r in accepted_subnet_routes if r.get("route") != cidr] + [
            {"route": cidr, "via": match.get("via")}
        ]
        settings["accepted_subnet_routes"] = accepted_subnet_routes
        save_settings(settings)
    return cidr, match.get("via")


def reject_route(output_dir: str, cidr: str) -> None:
    with _lock:
        settings = load_settings()
        accepted_subnet_routes = settings.get("accepted_subnet_routes") or []
        remaining = [r for r in accepted_subnet_routes if r.get("route") != cidr]
        if len(remaining) == len(accepted_subnet_routes):
            raise RouteError(f"{cidr!r} was not accepted.")
        settings["accepted_subnet_routes"] = remaining
        save_settings(settings)


def accept_exit_node(output_dir: str, via: str) -> None:
    available = get_available_routes(output_dir)
    if not any(r.get("kind") == "exit" and r.get("via") == via for r in available):
        raise RouteError(f"No exit node with via={via!r} is currently offered to this node.")
    with _lock:
        settings = load_settings()
        settings["accepted_exit_node"] = {"via": via}
        save_settings(settings)


def reject_exit_node(output_dir: str) -> None:
    with _lock:
        settings = load_settings()
        if not settings.get("accepted_exit_node"):
            raise RouteError("No exit node is currently accepted.")
        settings["accepted_exit_node"] = None
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
