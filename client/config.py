"""
Shared config and paths for ncclient (CLI, GUI clients).
Settings are stored in settings.json. Config dir is standalone (no token path).

One ncclient can be enrolled in several networks, each possibly on a different
Nebula Commander server. settings.json holds host-wide keys (interval, accept_dns,
exit_allow_lan, auto-update, exit_node) plus an "enrollments" list:

    {"id": "3f9a2c41", "server": "https://nc.example.com", "node_id": 12,
     "name": "office", "hostname": "laptop", "accepted_subnet_routes": [...]}

Each enrollment's state (config.yaml, dns-client.json, ...) lives in
<output_dir>/networks/<id>/ (enrollment_dir) and its token is stored under the same
id (client/token_store.py). Only one network on a host can use an exit node at a
time: exit_node is {"enrollment": id, "via": ip}.

Settings written by ncclient before 0.8.0 (server/node_id/accepted_* at the top
level, one token, state directly in output_dir) are converted in place by
migrate_to_enrollments().
"""
import json
import os
import secrets
import shutil
import sys

__all__ = [
    "config_dir", "settings_path", "load_settings", "save_settings",
    "enrollments", "find_enrollment", "enrollment_dir", "enrollment_view", "new_enrollment_id",
    "migrate_to_enrollments", "STATE_FILES",
]

# Per-enrollment files that used to sit directly in output_dir (moved by the migration).
STATE_FILES = ("config.yaml", "dns-client.json", "available-routes.json", "status.json", "nebula.log",
               "exit-bypass.json")
# Top-level keys that became per-enrollment ones.
_LEGACY_ENROLLMENT_KEYS = ("server", "node_id", "accepted_subnet_routes", "accepted_exit_node")


def config_dir() -> str:
    """Base directory for settings and other config (e.g. nebula downloads).
    NEBULA_COMMANDER_CONFIG_DIR overrides this when set - used by the Windows
    service (see client/windows/shared_paths.py) to share a machine-wide
    %ProgramData% location instead of the per-user default below."""
    override = os.environ.get("NEBULA_COMMANDER_CONFIG_DIR", "").strip()
    if override:
        return override
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
    """Write settings to disk atomically (temp file + os.replace), matching
    client/status_store.py's pattern - needed since client/service_api.py's
    D-Bus handler thread and the poll loop thread can both read/write this
    file within the same process, not just across separate CLI invocations."""
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, path)


# --- enrollments -----------------------------------------------------------------------

def new_enrollment_id() -> str:
    return secrets.token_hex(4)


def enrollments(settings: dict) -> list[dict]:
    """The enrollments in settings (a list of dicts with at least id and server)."""
    items = settings.get("enrollments")
    if not isinstance(items, list):
        return []
    return [e for e in items if isinstance(e, dict) and isinstance(e.get("id"), str) and e.get("id")]


def find_enrollment(settings: dict, key: "str | None") -> "dict | None":
    """An enrollment by id or name (case-insensitive). key None: the only enrollment,
    or None when there are several."""
    items = enrollments(settings)
    if key is None:
        return items[0] if len(items) == 1 else None
    for e in items:
        if e["id"] == key:
            return e
    lowered = key.lower()
    matches = [e for e in items if str(e.get("name") or "").lower() == lowered]
    return matches[0] if len(matches) == 1 else None


def enrollment_dir(output_dir: str, enrollment_id: str) -> str:
    """Where one enrollment's config.yaml, dns-client.json, status.json, ... live."""
    return os.path.join(os.path.expanduser(output_dir), "networks", enrollment_id)


def enrollment_view(settings: dict, enrollment_id: str) -> dict:
    """The settings one enrollment's poll loop sees, in the pre-0.8.0 single-network
    shape: host-wide keys plus this enrollment's server/node_id/accepted_subnet_routes,
    and accepted_exit_node only if the host's exit node belongs to this enrollment.
    host_exit_active tells every loop that some network on this host routes all
    traffic (Windows then binds every Nebula to the uplink)."""
    view = {k: v for k, v in settings.items() if k not in ("enrollments", "exit_node", *_LEGACY_ENROLLMENT_KEYS)}
    e = find_enrollment(settings, enrollment_id) or {}
    view["server"] = e.get("server")
    view["node_id"] = e.get("node_id")
    view["name"] = e.get("name") or ""
    view["accepted_subnet_routes"] = e.get("accepted_subnet_routes") or []
    exit_node = settings.get("exit_node") if isinstance(settings.get("exit_node"), dict) else None
    view["accepted_exit_node"] = (
        {"via": exit_node.get("via")} if exit_node and exit_node.get("enrollment") == enrollment_id else None
    )
    view["host_exit_active"] = bool(exit_node and exit_node.get("via"))
    return view


def migrate_to_enrollments(output_dir: "str | None" = None, log=None) -> bool:
    """Convert pre-0.8.0 settings (one network: server/node_id/accepted_* at the top
    level, the token stored without an id, state files directly in output_dir) to the
    enrollments layout. Idempotent; returns True when something was converted.

    The token is copied to the enrollment's id before the old one is removed, and the
    state files are moved, not copied, so a crash halfway leaves a state the next run
    finishes. ncclient before 0.8.0 can't read the result - downgrading needs a
    re-enroll."""
    from client import token_store

    settings = load_settings()
    has_legacy = any(k in settings for k in _LEGACY_ENROLLMENT_KEYS)
    legacy_token = token_store.get_token()
    if not has_legacy and not legacy_token:
        return False
    items = enrollments(settings)
    server = settings.get("server")
    node_id = settings.get("node_id")
    if server or legacy_token:
        existing = next((e for e in items if e.get("server") == server and e.get("node_id") == node_id), None)
        if existing is None:
            existing = {"id": new_enrollment_id(), "server": server, "node_id": node_id}
            items.append(existing)
        existing.setdefault("accepted_subnet_routes", settings.get("accepted_subnet_routes") or [])
        old_exit = settings.get("accepted_exit_node")
        if isinstance(old_exit, dict) and old_exit.get("via") and not settings.get("exit_node"):
            settings["exit_node"] = {"enrollment": existing["id"], "via": old_exit["via"]}
        if legacy_token and not token_store.get_token(existing["id"]):
            token_store.set_token(legacy_token, existing["id"])
        if output_dir:
            src_dir = os.path.expanduser(output_dir)
            dst_dir = enrollment_dir(output_dir, existing["id"])
            os.makedirs(dst_dir, exist_ok=True)
            for name in STATE_FILES:
                src = os.path.join(src_dir, name)
                if os.path.exists(src) and not os.path.exists(os.path.join(dst_dir, name)):
                    shutil.move(src, os.path.join(dst_dir, name))
    for k in _LEGACY_ENROLLMENT_KEYS:
        settings.pop(k, None)
    settings["enrollments"] = items
    save_settings(settings)
    if legacy_token:
        token_store.delete_token()
    if log:
        log(f"Converted settings to the multi-network layout ({len(items)} network(s))")
    return True
