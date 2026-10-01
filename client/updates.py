"""
Opt-in automatic client updates - the platform-independent part.

Off by default, and only switchable on the device by an administrator, through the
service (client/service_api.py's set_auto_update, reached via the Windows pipe, the
Linux D-Bus service or the CLI as root). The server can see the state in the
heartbeat but never change it.

What "on" means depends on how the client was installed (install_kind()):
- "windows": the service downloads the MSI named in the signed manifest and installs
  it during the configured window (client/windows/updater.py).
- "package" (deb/rpm from the official repo): a systemd timer runs
  ncclient-update.sh during the window (client/linux/auto_update.py).
- "nixos": notify only. The version is pinned by the machine's flake, so the client
  checks the signed manifest once a day and reports what's available, with the
  commands to update, but never changes the system.
- anything else (Docker, Flatpak, pip, a bare binary): not supported.

The manifest (https://pkgs.nebulacommander.com/updates/latest.json, signed by CI -
see .github/workflows/publish-package-repo.yml) is trusted only with a valid Ed25519
signature from a key in client/update_keys.py. Dev builds (client/version.py) never
install anything.
"""
from __future__ import annotations

import base64
import binascii
import datetime as _dt
import json
import os
import random
import re
import sys

from client import version as _version
from client.config import config_dir, load_settings

__all__ = [
    "UpdateError",
    "DEFAULT_SETTINGS",
    "install_kind",
    "auto_update_settings",
    "validate_settings",
    "mode",
    "parse_version",
    "is_newer",
    "parse_hhmm",
    "next_run",
    "window_end_after",
    "verify_manifest",
    "fetch_manifest",
    "evaluate",
    "check",
    "load_status",
    "save_status",
    "update_status_path",
    "nixos_update_commands",
]

MANIFEST_URL = "https://pkgs.nebulacommander.com/updates/latest.json"
# Every asset URL in the manifest must start with this - even a validly signed
# manifest can't point the updater anywhere else.
ALLOWED_ASSET_PREFIX = "https://github.com/NixRTR/nebula-commander/releases/download/"
SETTINGS_KEY = "auto_update"
DEFAULT_SETTINGS = {"enabled": False, "window_start": "02:00", "window_end": "05:00"}
SUPPORTED_KINDS = ("windows", "package", "nixos")
_MAX_MANIFEST_BYTES = 64 * 1024
_HTTP_TIMEOUT = 30
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
# Stable releases only: no pre-releases, no build metadata.
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class UpdateError(Exception):
    """A check or install failed; str(e) is user-facing."""


# --- installation kind / settings -------------------------------------------------

def install_kind() -> str:
    """windows | package | nixos | unsupported.

    deb/rpm units and the NixOS module set NEBULA_COMMANDER_INSTALL_KIND; a frozen
    Windows build is always the MSI install (the service and the bundled ncclient)."""
    kind = os.environ.get("NEBULA_COMMANDER_INSTALL_KIND", "").strip().lower()
    if kind in SUPPORTED_KINDS:
        return kind
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        return "windows"
    return "unsupported"


def parse_hhmm(value: str) -> "tuple[int, int]":
    m = _HHMM_RE.match(value or "")
    if not m:
        raise UpdateError(f"Invalid time {value!r}: use HH:MM (24-hour), e.g. 02:00")
    return int(m.group(1)), int(m.group(2))


def validate_settings(enabled: bool, window_start: str, window_end: str) -> dict:
    """Normalized auto_update settings; raises UpdateError on a bad window."""
    parse_hhmm(window_start)
    parse_hhmm(window_end)
    if window_start == window_end:
        raise UpdateError("The update window's start and end must differ")
    return {"enabled": bool(enabled), "window_start": window_start, "window_end": window_end}


def auto_update_settings(settings: "dict | None" = None) -> dict:
    """settings.json's auto_update block merged over the defaults (invalid values fall
    back to the defaults rather than breaking the service)."""
    raw = (load_settings() if settings is None else settings).get(SETTINGS_KEY)
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        merged.update({k: raw[k] for k in DEFAULT_SETTINGS if k in raw})
    try:
        return validate_settings(merged["enabled"], merged["window_start"], merged["window_end"])
    except UpdateError:
        return dict(DEFAULT_SETTINGS, enabled=bool(merged.get("enabled")))


def mode(settings: "dict | None" = None, kind: "str | None" = None) -> str:
    """What the heartbeat reports: off | install | notify."""
    kind = kind or install_kind()
    if kind not in SUPPORTED_KINDS or not auto_update_settings(settings)["enabled"]:
        return "off"
    return "notify" if kind == "nixos" else "install"


# --- versions ------------------------------------------------------------------------

def parse_version(value: str) -> "tuple[int, int, int] | None":
    m = _VERSION_RE.match((value or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def is_newer(candidate: str, current: str) -> bool:
    """True only if both are stable versions and candidate > current. A dev build or
    any pre-release on either side is never "older", so it is never replaced."""
    c, cur = parse_version(candidate), parse_version(current)
    return c is not None and cur is not None and c > cur


# --- the window ----------------------------------------------------------------------

def _window_bounds(day: _dt.date, start: str, end: str) -> "tuple[_dt.datetime, _dt.datetime]":
    sh, sm = parse_hhmm(start)
    eh, em = parse_hhmm(end)
    ws = _dt.datetime.combine(day, _dt.time(sh, sm))
    length = ((eh * 60 + em) - (sh * 60 + sm)) % (24 * 60)
    return ws, ws + _dt.timedelta(minutes=length)


def next_run(now: _dt.datetime, start: str, end: str, rng: "random.Random | None" = None) -> _dt.datetime:
    """A random moment in the first window (local time) that hasn't ended yet, and
    not before `now`. Windows may wrap past midnight (e.g. 23:00-01:00)."""
    rng = rng or random.SystemRandom()
    for offset in (-1, 0, 1):
        ws, we = _window_bounds(now.date() + _dt.timedelta(days=offset), start, end)
        if now < we:
            lo = max(ws, now)
            return lo + _dt.timedelta(seconds=rng.uniform(0, (we - lo).total_seconds()))
    raise AssertionError("unreachable: tomorrow's window always ends after now")


def window_end_after(moment: _dt.datetime, start: str, end: str) -> _dt.datetime:
    """End of the window `moment` falls in (or of the next one) - after a run, the
    scheduler waits for this before picking the next slot, so it runs once a window."""
    for offset in (-1, 0, 1):
        ws, we = _window_bounds(moment.date() + _dt.timedelta(days=offset), start, end)
        if moment < we:
            return we
    raise AssertionError("unreachable")


# --- the signed manifest -------------------------------------------------------------

def _trusted_keys() -> "list[bytes]":
    from client.update_keys import PUBLIC_KEYS

    keys = list(PUBLIC_KEYS)
    # A local test build may bake in an extra key (client/stamp_version.py
    # --test-key). CI never does, and it can't be set at runtime.
    test = getattr(_version, "UPDATE_TEST_KEY", None)
    if test:
        keys.append(test)
    return [base64.b64decode(k) for k in keys]


def manifest_url() -> str:
    return getattr(_version, "UPDATE_TEST_MANIFEST_URL", None) or MANIFEST_URL


def verify_manifest(body: bytes, signature: bytes, keys: "list[bytes] | None" = None) -> dict:
    """Parse the manifest once its detached signature (base64 of a raw 64-byte
    Ed25519 signature over the exact body bytes) checks out against a trusted key."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        sig = base64.b64decode(signature.strip(), validate=True)
    except (binascii.Error, ValueError) as e:
        raise UpdateError("Update manifest signature is malformed") from e
    for raw in _trusted_keys() if keys is None else keys:
        try:
            Ed25519PublicKey.from_public_bytes(raw).verify(sig, body)
            break
        except (InvalidSignature, ValueError):
            continue
    else:
        raise UpdateError("Update manifest signature is not valid - refusing to use it")

    try:
        manifest = json.loads(body.decode("utf-8"))
    except ValueError as e:
        raise UpdateError("Update manifest is not valid JSON") from e
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise UpdateError("Update manifest has an unknown format")
    if parse_version(str(manifest.get("version", ""))) is None:
        raise UpdateError("Update manifest names no stable version")
    assets = manifest.get("assets") or {}
    if not isinstance(assets, dict):
        raise UpdateError("Update manifest assets are malformed")
    for name, asset in assets.items():
        url = (asset or {}).get("url", "") if isinstance(asset, dict) else ""
        sha = (asset or {}).get("sha256", "") if isinstance(asset, dict) else ""
        if not url.startswith(ALLOWED_ASSET_PREFIX) or ".." in url:
            raise UpdateError(f"Update manifest asset {name!r} points outside the official releases")
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise UpdateError(f"Update manifest asset {name!r} has no valid SHA-256")
    return manifest


def _get(url: str) -> bytes:
    import requests

    try:
        with requests.get(url, headers={"User-Agent": f"ncclient/{_version.VERSION}"}, timeout=_HTTP_TIMEOUT, stream=True) as r:
            r.raise_for_status()
            data = b""
            for chunk in r.iter_content(chunk_size=8192):
                data += chunk
                if len(data) > _MAX_MANIFEST_BYTES:
                    raise UpdateError("Update manifest is too large")
            return data
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(f"Could not fetch {url}: {e}") from e


def fetch_manifest(url: "str | None" = None) -> dict:
    url = url or manifest_url()
    return verify_manifest(_get(url), _get(url + ".sig"))


# --- deciding ------------------------------------------------------------------------

def evaluate(manifest: dict, kind: str, current: "str | None" = None,
             git_commit: "str | None" = None, source_date: "int | None" = None) -> "str | None":
    """The manifest's version if it's an update for this install, else None.

    A Nix build has no version number (only the commit it was built from - see
    nix/client-package.nix), so it's compared by commit and commit time instead."""
    current = _version.VERSION if current is None else current
    git_commit = _version.GIT_COMMIT if git_commit is None else git_commit
    source_date = _version.SOURCE_DATE if source_date is None else source_date
    latest = manifest["version"]
    if not _version.is_dev_build(current):
        return latest if is_newer(latest, current) else None
    if kind == "nixos" and git_commit:
        if manifest.get("git_commit") == git_commit:
            return None
        commit_time = manifest.get("commit_time")
        if isinstance(commit_time, int) and isinstance(source_date, int) and commit_time > source_date:
            return latest
    return None


def nixos_update_commands(manifest_or_tag: "dict | str") -> "list[str]":
    tag = manifest_or_tag.get("tag") if isinstance(manifest_or_tag, dict) else manifest_or_tag
    return [
        "nix flake update nebula-commander",
        f"# or, if your flake pins a release: github:NixRTR/nebula-commander/{tag}",
        "sudo nixos-rebuild switch",
    ]


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def check(kind: "str | None" = None) -> dict:
    """Fetch + verify the manifest and record the result in update-status.json.
    Returns the updated status, plus "manifest" (not persisted) when an update is
    available, for the platform installer to act on. Never installs anything."""
    kind = kind or install_kind()
    status = load_status()
    status["last_check"] = _now_iso()
    try:
        manifest = fetch_manifest()
    except UpdateError as e:
        status.update(last_result="error", last_error=str(e))
        save_status(status)
        return status
    available = evaluate(manifest, kind)
    status.update(last_result="update_available" if available else "up_to_date",
                  last_error=None, latest_version=manifest["version"], available_version=available)
    if available and kind == "nixos":
        status["instructions"] = nixos_update_commands(manifest)
    else:
        status.pop("instructions", None)
    save_status(status)
    return {**status, "manifest": manifest} if available else status


# --- update-status.json --------------------------------------------------------------

def update_status_path() -> str:
    return os.path.join(config_dir(), "update-status.json")


def load_status() -> dict:
    try:
        with open(update_status_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_status(status: dict) -> None:
    path = update_status_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in status.items() if k != "manifest"}, f, indent=2)
    os.replace(tmp, path)
