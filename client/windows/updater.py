"""
Automatic updates for the Windows install (install kind "windows", client/updates.py).

A thread in the service (service.py) sleeps until a random moment in the configured
window, checks the signed manifest and, if there's a newer release and automatic
updates are on:
  1. downloads the MSI named in the manifest into %ProgramData%\\nebula-commander\\
     updates\\ (SYSTEM/Administrators-only, see harden.py),
  2. checks its SHA-256 against the signed manifest,
  3. records pending-update.json, and
  4. starts msiexec detached from the service (its own process tree, outside the
     service's job), because the MSI stops this service while it upgrades it.
When the upgraded service starts, record_pending_result() compares the running
version with what was being installed and records success or failure.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import subprocess  # nosec B404 - fixed msiexec argv, no shell
import threading
from typing import Callable

from client import updates
from client.config import config_dir
from client.version import VERSION, is_dev_build

ASSET_KEY = "windows-amd64"  # the only MSI there is; it also runs on ARM64
_HTTP_TIMEOUT = 60
_IDLE_RECHECK = 3600  # seconds; re-read settings at least this often while off

# Process creation flags for a child that must outlive this service.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def updates_dir() -> str:
    return os.path.join(config_dir(), "updates")


def _pending_path() -> str:
    return os.path.join(updates_dir(), "pending-update.json")


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def download_verified(url: str, sha256: str, dest: str) -> None:
    """Stream url to dest, keeping it only if its SHA-256 matches the signed manifest."""
    import requests

    part = dest + ".part"
    h = hashlib.sha256()
    try:
        with requests.get(url, headers={"User-Agent": f"ncclient/{VERSION}"}, timeout=_HTTP_TIMEOUT, stream=True) as r:
            r.raise_for_status()
            with open(part, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    h.update(chunk)
                    f.write(chunk)
    except Exception as e:
        _unlink(part)
        raise updates.UpdateError(f"Download failed ({url}): {e}") from e
    if h.hexdigest() != sha256:
        _unlink(part)
        raise updates.UpdateError("The downloaded installer doesn't match the signed manifest - discarded")
    os.replace(part, dest)


def _unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _clean_old_installers(keep: str) -> None:
    try:
        for name in os.listdir(updates_dir()):
            path = os.path.join(updates_dir(), name)
            if path != keep and name.lower().endswith((".msi", ".part")):
                _unlink(path)
    except OSError:
        pass


def msiexec_argv(msi: str, log: str) -> "list[str]":
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return [os.path.join(system_root, "System32", "msiexec.exe"), "/i", msi, "/qn", "/norestart", "/l*v", log]


def start_install(manifest: dict, log: Callable[[str], None]) -> dict:
    """Download, verify and launch the MSI for `manifest`. Returns the pending record."""
    asset = (manifest.get("assets") or {}).get(ASSET_KEY)
    if not asset:
        raise updates.UpdateError(f"The update manifest has no {ASSET_KEY} installer")
    os.makedirs(updates_dir(), exist_ok=True)
    version = manifest["version"]
    msi = os.path.join(updates_dir(), f"NebulaCommander-{version}.msi")
    if not (os.path.isfile(msi) and _sha256_file(msi) == asset["sha256"]):
        download_verified(asset["url"], asset["sha256"], msi)
    _clean_old_installers(keep=msi)
    msi_log = os.path.join(updates_dir(), f"install-{version}.log")
    pending = {"version": version, "from_version": VERSION, "msi": msi, "log": msi_log,
               "started": updates._now_iso()}
    with open(_pending_path(), "w", encoding="utf-8") as f:
        json.dump(pending, f, indent=2)
    log(f"Auto-update: installing Nebula Commander {version} (log: {msi_log})")
    flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(  # nosec B603 - fixed argv: msiexec + our verified MSI
            msiexec_argv(msi, msi_log), creationflags=flags | _CREATE_BREAKAWAY_FROM_JOB,
            close_fds=True, cwd=updates_dir(),
        )
    except PermissionError:
        # In a job that forbids breakaway: still detached, which is enough when the
        # job doesn't kill its processes on close (the SCM doesn't put services in one).
        subprocess.Popen(  # nosec B603
            msiexec_argv(msi, msi_log), creationflags=flags, close_fds=True, cwd=updates_dir(),
        )
    return pending


def record_pending_result(log: Callable[[str], None]) -> None:
    """Called at service start: did the install we launched last time succeed?"""
    try:
        with open(_pending_path(), "r", encoding="utf-8") as f:
            pending = json.load(f)
    except (OSError, ValueError):
        return
    status = updates.load_status()
    target = pending.get("version")
    if VERSION == target:
        status.update(last_install_result="updated", last_install_error=None,
                      last_install_changes={"Nebula Commander": f"{pending.get('from_version')} -> {target}"},
                      available_version=None)
        log(f"Auto-update: now running {target}")
        _unlink(pending.get("msi", ""))
    elif VERSION == pending.get("from_version"):
        # The service restarted without the upgrade having happened (MSI failed and
        # rolled back, or hasn't run). Leave the MSI so the next window can retry.
        status.update(last_install_result="error",
                      last_install_error=f"Installing {target} failed - see {pending.get('log')}")
        log(f"Auto-update: installing {target} failed - see {pending.get('log')}")
    else:
        status.update(last_install_result="updated", last_install_error=None)
    status["last_install_attempt"] = pending.get("started")
    updates.save_status(status)
    _unlink(_pending_path())


class Updater(threading.Thread):
    """Sleeps until the next window slot, then checks and (if on) installs."""

    def __init__(self, stop_event: threading.Event, log: Callable[[str], None]) -> None:
        super().__init__(name="auto-update", daemon=True)
        self._stop_event = stop_event
        self._log = log
        self._wake = threading.Event()
        self._run_now = False
        self._lock = threading.Lock()

    # --- ServiceHooks side -----------------------------------------------------------

    def reschedule(self) -> None:
        self._wake.set()

    def check_now(self) -> None:
        with self._lock:
            self._run_now = True
        self._wake.set()

    # --- thread ------------------------------------------------------------------------

    def run(self) -> None:
        try:
            record_pending_result(self._log)
        except Exception as e:  # never let bookkeeping stop updates
            self._log(f"Auto-update: could not record the last install: {e}")
        not_before: "_dt.datetime | None" = None
        while not self._stop_event.is_set():
            try:
                not_before = self._tick(not_before)
            except Exception as e:
                self._log(f"Auto-update: {e}")
                self._sleep(_IDLE_RECHECK)

    def _sleep(self, seconds: float) -> bool:
        """Wait up to `seconds`; True if woken early (settings changed / check now)."""
        woke = self._wake.wait(timeout=max(0.0, seconds))
        self._wake.clear()
        return woke or self._stop_event.is_set()

    def _take_run_now(self) -> bool:
        with self._lock:
            run_now, self._run_now = self._run_now, False
        return run_now

    def _tick(self, not_before: "_dt.datetime | None") -> "_dt.datetime | None":
        settings = updates.auto_update_settings()
        if self._take_run_now():
            self.run_once(install=settings["enabled"])
            return not_before
        if not settings["enabled"]:
            self._sleep(_IDLE_RECHECK)
            return None
        now = _dt.datetime.now()
        start = max(now, not_before) if not_before else now
        when = updates.next_run(start, settings["window_start"], settings["window_end"])
        if self._sleep((when - now).total_seconds()):
            return not_before  # settings changed or "check now": re-plan
        self.run_once(install=True)
        return updates.window_end_after(when, settings["window_start"], settings["window_end"])

    def run_once(self, install: bool) -> dict:
        result = updates.check("windows")
        manifest = result.pop("manifest", None)
        if result.get("last_result") == "error":
            self._log(f"Auto-update check failed: {result.get('last_error')}")
            return result
        if not manifest or not install or is_dev_build():
            return result
        status = updates.load_status()
        status["last_install_attempt"] = updates._now_iso()
        try:
            start_install(manifest, self._log)
            status.update(last_install_result="installing", last_install_error=None)
        except (updates.UpdateError, OSError) as e:
            status.update(last_install_result="error", last_install_error=str(e))
            self._log(f"Auto-update install failed: {e}")
        updates.save_status(status)
        return status
