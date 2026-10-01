"""
Auto-update for deb/rpm installs (install kind "package", see client/updates.py).

The upgrade itself is done by ncclient-update.service (a oneshot running
/usr/lib/nebula-commander/ncclient-update.sh), started by ncclient-update.timer
during the configured window. It runs in its own unit, outside ncclient.service's
cgroup, so the package's postinst restarting ncclient can't kill it mid-upgrade.

Only installs that already use the official signed repository are supported: the
script upgrades from that repo and nothing else, with signature checks left on.
"""
from __future__ import annotations

import os
import subprocess  # nosec B404 - fixed argv, no shell

from client.updates import UpdateError, parse_hhmm

REPO_HOST = "pkgs.nebulacommander.com"
REPO_FILES = (
    "/etc/apt/sources.list.d/nebula-commander.sources",
    "/etc/apt/sources.list.d/nebula-commander.list",
    "/etc/yum.repos.d/nebula-commander.repo",
    "/etc/zypp/repos.d/nebula-commander.repo",
)
REPO_DOCS = "https://nebulacdr.com/docs/usage/ncclient/installation/linux/"
TIMER = "ncclient-update.timer"
SERVICE = "ncclient-update.service"
DROPIN_DIR = "/etc/systemd/system/ncclient-update.timer.d"
DROPIN = os.path.join(DROPIN_DIR, "window.conf")


def repo_configured(files: "tuple[str, ...]" = REPO_FILES) -> bool:
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                if REPO_HOST in f.read():
                    return True
        except OSError:
            continue
    return False


def timer_dropin(window_start: str, window_end: str) -> str:
    """OnCalendar fires at the window's start; RandomizedDelaySec spreads the run
    over the window. Persistent=false: a machine that was off during the window
    waits for the next one rather than upgrading the moment it boots."""
    sh, sm = parse_hhmm(window_start)
    eh, em = parse_hhmm(window_end)
    length = ((eh * 60 + em) - (sh * 60 + sm)) % (24 * 60)
    return (
        "# Written by ncclient (auto-update window). Change it with\n"
        "# `ncclient auto-update enable --window HH:MM-HH:MM` or the desktop app.\n"
        "[Timer]\n"
        "OnCalendar=\n"
        f"OnCalendar=*-*-* {sh:02d}:{sm:02d}:00\n"
        f"RandomizedDelaySec={length * 60}\n"
        "Persistent=false\n"
    )


def _systemctl(*args: str) -> None:
    try:
        r = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=60)  # nosec B603 B607
    except (OSError, subprocess.SubprocessError) as e:
        raise UpdateError(f"systemctl {' '.join(args)} failed: {e}") from e
    if r.returncode != 0:
        raise UpdateError(f"systemctl {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")


def apply(enabled: bool, window_start: str, window_end: str) -> None:
    """Make the timer match the settings. Refuses to turn on without the repo."""
    if enabled and not repo_configured():
        raise UpdateError(
            "Automatic updates need the official Nebula Commander package repository, "
            f"which isn't configured on this machine. Add it first: {REPO_DOCS}"
        )
    if enabled:
        os.makedirs(DROPIN_DIR, exist_ok=True)
        tmp = DROPIN + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(timer_dropin(window_start, window_end))
        os.replace(tmp, DROPIN)
        _systemctl("daemon-reload")
        _systemctl("enable", "--now", TIMER)
        # re-arm with the new window if it was already running
        _systemctl("restart", TIMER)
    else:
        _systemctl("disable", "--now", TIMER)


def run_now() -> None:
    """Start an upgrade right away (in its own unit, so it outlives our restart)."""
    _systemctl("start", "--no-block", SERVICE)


def reconcile(settings: dict, log) -> None:
    """On service start: make the timer match settings.json (e.g. after a restore,
    or a manual `systemctl disable`). Never raises."""
    try:
        apply(settings["enabled"], settings["window_start"], settings["window_end"])
    except UpdateError as e:
        log(f"Auto-update: could not apply settings: {e}")


# --- the upgrade itself (ncclient-update.service -> `ncclient auto-update run-upgrade`) ---

APT_SOURCES = "/etc/apt/sources.list.d/nebula-commander.sources"
_PKG_PREFIX = "nebula-commander-"


def _run(argv: "list[str]", log, timeout: int = 1800) -> "subprocess.CompletedProcess[str]":
    log("$ " + " ".join(argv))
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", LC_ALL="C")
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)  # nosec B603
    for line in (r.stdout + r.stderr).splitlines():
        log("  " + line)
    return r


def _package_manager() -> "str | None":
    import shutil

    for pm in ("apt-get", "dnf", "zypper"):
        if shutil.which(pm):
            return pm
    return None


def installed_packages(pm: str) -> "dict[str, str]":
    """Installed nebula-commander-* packages -> version."""
    if pm == "apt-get":
        argv = ["dpkg-query", "-W", "-f=${Package}\t${Version}\t${db:Status-Abbrev}\n", _PKG_PREFIX + "*"]
    else:
        argv = ["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}\tii\n", _PKG_PREFIX + "*"]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout  # nosec B603
    except (OSError, subprocess.SubprocessError):
        return {}
    pkgs = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith(_PKG_PREFIX) and parts[2].strip().startswith("ii"):
            pkgs[parts[0]] = parts[1]
    return pkgs


def upgrade_commands(pm: str, packages: "list[str]", apt_sources: "str | None" = None) -> "list[list[str]]":
    """Refresh our repo's metadata and upgrade only the given (already installed)
    packages, non-interactively. Signature checks stay on; keys are never imported."""
    if pm == "apt-get":
        refresh = ["apt-get", "update"]
        if apt_sources:
            # Only our repository's lists, leaving every other source untouched.
            refresh += ["-o", f"Dir::Etc::sourcelist={apt_sources}", "-o", "Dir::Etc::sourceparts=-",
                        "-o", "APT::Get::List-Cleanup=0"]
        return [refresh, ["apt-get", "install", "--only-upgrade", "-y",
                          "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold",
                          *packages]]
    if pm == "dnf":
        return [["dnf", "-y", "--refresh", "upgrade", *packages]]
    if pm == "zypper":
        return [["zypper", "--non-interactive", "refresh", "nebula-commander"],
                ["zypper", "--non-interactive", "update", *packages]]
    raise UpdateError(f"Unsupported package manager {pm!r}")


def run_upgrade(log=print) -> dict:
    """Upgrade the installed Nebula Commander packages from the official repo and
    record the outcome in update-status.json. Returns the status."""
    from client.updates import _now_iso, load_status, save_status

    status = load_status()
    status["last_install_attempt"] = _now_iso()
    try:
        if not repo_configured():
            raise UpdateError(f"The official package repository isn't configured ({REPO_DOCS})")
        pm = _package_manager()
        if pm is None:
            raise UpdateError("No supported package manager (apt-get, dnf or zypper) found")
        before = installed_packages(pm)
        if not before:
            raise UpdateError("No nebula-commander packages are installed")
        sources = APT_SOURCES if os.path.isfile(APT_SOURCES) else None
        for argv in upgrade_commands(pm, sorted(before), sources):
            r = _run(argv, log)
            if r.returncode != 0:
                tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or [""]
                raise UpdateError(f"{argv[0]} failed (exit {r.returncode}): {tail[0]}")
        after = installed_packages(pm)
        changed = {p: f"{before[p]} -> {v}" for p, v in after.items() if before.get(p) != v}
        status.update(last_install_result="updated" if changed else "up_to_date",
                      last_install_error=None, last_install_changes=changed)
        if changed:
            status["available_version"] = None
        log(f"Auto-update: {'upgraded ' + ', '.join(f'{p} {c}' for p, c in changed.items()) if changed else 'already up to date'}")
    except (UpdateError, OSError, subprocess.SubprocessError) as e:
        status.update(last_install_result="error", last_install_error=str(e))
        log(f"Auto-update failed: {e}")
    save_status(status)
    return status
