"""
Split-horizon DNS apply/remove for ncclient.
Linux: detects how the host manages DNS and uses the matching mechanism (see
_linux_detect_backend): systemd-resolved per-link DNS on the Nebula interface (also used when
NetworkManager delegates to resolved), NetworkManager's dnsmasq plugin (switching
NetworkManager to it if needed), a standalone dnsmasq service, or - last resort, not real
split-horizon - appending to /etc/resolv.conf. ensure_split_horizon_dns() re-checks it each
poll and re-applies if something (a resolver restart, nebula recreating its interface)
undid it.
Windows: NRPT (Name Resolution Policy Table).

Windows NRPT testing: nslookup uses the default DNS server directly and bypasses NRPT.
To verify split-horizon, use: Resolve-DnsName <host>.nebula.example.com
or: ping <host>.nebula.example.com (uses system resolver, which respects NRPT).
"""
import json
import os
import re
import shutil
import subprocess  # nosec B404 - used with shell=False and validated/fixed args
import sys
import time

# When calling systemctl, avoid passing PyInstaller lib path (same as ncclient)
_SYSTEM_LIBRARY_ENV_STRIP = ("LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT", "LIBPATH")

# Linux paths for idempotent apply/remove.
# LINUX_DROPIN, LINUX_DNSMASQ_CONF, LINUX_RESOLV_CONF, LINUX_RESOLV_BACKUP, and RESOLV_MARKER
# are duplicated in contrib/dns-apply-linux.sh, a manual fallback script for when this daemon
# lacks privilege to self-apply (see _elevation_message() below). That script only covers the
# systemd-resolved/dnsmasq/resolv.conf backends (not NetworkManager), so the LINUX_NM_* paths
# and LINUX_NETWORKD_NETWORK below are NOT mirrored there. contrib/check_dns_paths_sync.py checks
# the ones that should match stay in sync - update both places if you change a path here.
# LINUX_DROPIN (a global resolved drop-in) and LINUX_NETWORKD_NETWORK are no longer written by
# this module - it now sets per-link DNS on the Nebula interface instead - but are still
# removed if an older ncclient left them behind.
LINUX_DROPIN = "/etc/systemd/resolved.conf.d/nebula-dns.conf"
LINUX_DNSMASQ_CONF = "/etc/dnsmasq.d/nebula-commander.conf"
LINUX_NETWORKD_NETWORK = "/etc/systemd/network/70-nebula-commander.network"
LINUX_RESOLV_CONF = "/etc/resolv.conf"
LINUX_RESOLV_BACKUP = "/etc/resolv.conf.nebula-commander.bak"
RESOLV_MARKER = "# nebula-commander"
# NetworkManager: its dnsmasq plugin reads dnsmasq.d/; conf.d/ switches it to that plugin and
# keeps it from taking over the Nebula tun device.
LINUX_NM_DNSMASQ_CONF = "/etc/NetworkManager/dnsmasq.d/nebula-commander.conf"
LINUX_NM_DNS_MODE_CONF = "/etc/NetworkManager/conf.d/90-nebula-commander-dns.conf"
LINUX_NM_UNMANAGED_CONF = "/etc/NetworkManager/conf.d/91-nebula-commander-unmanaged.conf"
# A host can run one ncclient per network, each on its own tun device, so the dnsmasq
# files are per instance: nebula-commander-<tun_dev>.conf next to LINUX_DNSMASQ_CONF and
# LINUX_NM_DNSMASQ_CONF (see _instance_conf). Those two unsuffixed paths are what ncclient
# before 0.8.0 wrote; the instance on LEGACY_TUN_DEV removes them. The shared conf.d files
# are never removed at runtime: LINUX_NM_UNMANAGED_CONF is static and only the package's
# uninstall removes it, and LINUX_NM_DNS_MODE_CONF goes once no instance file is left.
# /etc/resolv.conf has a single marker block, so that fallback backend is single-instance.
LEGACY_TUN_DEV = "nebula1"

# Mirrored in contrib/dns-apply-windows.ps1 - see contrib/check_dns_paths_sync.py.
NRPT_RULE_NAME = "NebulaCommander"

# Domain/DNS-server values come from the backend's dns-client-config response,
# not a hardcoded literal - reject anything that isn't hostname/IP-shaped before
# it reaches a PowerShell -Command string (interpolated, not passed as a separate
# argv token) or gets written into a Linux resolver config file.
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
_IP_RE = re.compile(r"^[0-9A-Fa-f:.]+$")  # covers IPv4 and IPv6 literals
# tun.dev also comes from the backend (the node's config) and is written into a
# NetworkManager conf file - Linux interface-name shaped only.
_TUN_DEV_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,15}$")


def _is_safe_dns_value(value: str) -> bool:
    return bool(_HOSTNAME_RE.match(value)) or bool(_IP_RE.match(value))


def _which(name: str) -> str:
    """Resolve a system binary to an absolute path before spawning it, so we
    don't rely on subprocess's own PATH search (falls back to the bare name
    if not found, so behavior/error messages are unchanged when it's missing)."""
    return shutil.which(name) or name


def _env_for_system_binaries():
    env = os.environ.copy()
    for key in _SYSTEM_LIBRARY_ENV_STRIP:
        env.pop(key, None)
    return env

# Get rule names (GUIDs) via CIM; remove via Remove-DnsClientNrptRule (CIM delete doesn't work for this class).
# One Remove-DnsClientNrptRule per invocation to avoid pipeline/EndProcessing prompt in -NonInteractive.


def _can_apply() -> bool:
    """True if we have privileges to apply (root on Linux, elevated on Windows)."""
    if sys.platform == "win32":
        try:
            from client.ncclient import is_process_elevated
            return is_process_elevated()
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return True


def _elevation_message() -> str:
    if sys.platform == "win32":
        return "Run as Administrator to apply DNS with --accept-dns, or run the contrib script manually: contrib/dns-apply-windows.ps1"
    return (
        "Run as root to apply DNS with --accept-dns, or run the contrib script manually: "
        "contrib/dns-apply-linux.sh (covers systemd-resolved/dnsmasq/resolv.conf only, "
        "not NetworkManager or systemd-networkd)"
    )


def _safe_tun_dev(tun_dev: str | None) -> str | None:
    """tun_dev if it is interface-name shaped, else None (falls back to name matching)."""
    if tun_dev and _TUN_DEV_RE.match(tun_dev) and tun_dev not in (".", ".."):
        return tun_dev
    return None


def apply_split_horizon_dns(
    config_path: str | None = None,
    config_dict: dict | None = None,
    tun_dev: str | None = None,
) -> bool:
    """
    Apply split-horizon DNS from dns-client.json path or from a dict.
    config_path: path to dns-client.json (read and parsed).
    config_dict: optional {"domain": str, "dns_servers": list[str]} (overrides config_path if both set).
    tun_dev: this node's Nebula tun device (its config's `tun.dev`). Without it, Linux falls
    back to the first interface whose name contains "nebula".
    Returns True if applied, False if skipped (no config, no privilege, or error).
    """
    if not _can_apply():
        print(_elevation_message(), file=sys.stderr)
        return False

    data = config_dict
    if data is None and config_path and os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
    if not data or not isinstance(data.get("domain"), str):
        return False
    domain = (data.get("domain") or "").strip()
    servers = data.get("dns_servers") or []
    if not domain or not servers:
        return False
    servers = [s.strip() for s in servers if isinstance(s, str) and s.strip()]
    if not servers:
        return False

    if not _is_safe_dns_value(domain) or not all(_is_safe_dns_value(s) for s in servers):
        print(
            "Refusing to apply DNS: domain or server contains disallowed characters",
            file=sys.stderr,
        )
        return False

    if sys.platform == "win32":
        return _apply_windows(domain, servers, _safe_tun_dev(tun_dev))
    return _apply_linux(domain, servers, _safe_tun_dev(tun_dev))


def remove_split_horizon_dns(tun_dev: str | None = None) -> bool:
    """
    Remove this instance's split-horizon DNS (per-instance files or NRPT rule). Other
    ncclient instances on the host keep theirs.
    Returns True if removed or already absent, False if no privilege or error.
    """
    if not _can_apply():
        return False
    if sys.platform == "win32":
        return _remove_windows(_safe_tun_dev(tun_dev))
    return _remove_linux(_safe_tun_dev(tun_dev))


def ensure_split_horizon_dns(config_dict: dict, tun_dev: str | None = None) -> bool:
    """
    Re-check that split-horizon DNS from config_dict is still in effect and re-apply it if
    not (resolver restarted, nebula recreated its interface, an earlier apply failed because
    the interface wasn't up yet). Cheap when nothing changed. Windows NRPT rules persist, so
    this is a no-op there. Returns True if DNS is in effect afterwards.
    """
    if sys.platform == "win32":
        return True
    a = _linux_applied
    if (
        a
        and a["domain"] == (config_dict.get("domain") or "").strip()
        and a["servers"] == [s.strip() for s in (config_dict.get("dns_servers") or []) if isinstance(s, str) and s.strip()]
        and a["tun_dev"] == _safe_tun_dev(tun_dev)
        and _linux_verify_applied()
    ):
        return True
    if a:
        print("Split-horizon DNS is no longer in effect; re-applying.", file=sys.stderr)
    return apply_split_horizon_dns(config_dict=config_dict, tun_dev=tun_dev)


def _run_systemctl(*args: str) -> bool:
    try:
        subprocess.run(  # nosec B603 - fixed command resolved via shutil.which, shell=False
            [_which("systemctl"), *args],
            check=True,
            capture_output=True,
            timeout=30,
            env=_env_for_system_binaries(),
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _run(cmd: list[str], timeout: float = 10) -> "subprocess.CompletedProcess | None":
    """Run a system binary (resolved via _which), returning None if it's missing or hangs."""
    try:
        return subprocess.run(  # nosec B603 - fixed command resolved via shutil.which, shell=False
            [_which(cmd[0]), *cmd[1:]],
            capture_output=True,
            timeout=timeout,
            text=True,
            env=_env_for_system_binaries(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _write_if_changed(path: str, content: str) -> bool:
    """Write content to path (creating its directory). Returns True if the file changed."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            if f.read() == content:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def _remove_file(path: str) -> bool:
    """Remove path if present. Returns True if something was removed."""
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


# Only print a status line when it differs from the last one, so a backend that keeps
# failing (retried every poll by ensure_split_horizon_dns) doesn't flood the journal.
_last_report: "str | None" = None


def _report(message: str) -> None:
    global _last_report
    if message != _last_report:
        print(message, file=sys.stderr)
        _last_report = message


# ---- Detection ----


def _linux_resolved_available() -> bool:
    return _run_systemctl("is-active", "systemd-resolved")


def _linux_resolv_conf_uses_resolved() -> bool:
    """True if /etc/resolv.conf sends queries to systemd-resolved (stub or its generated file)."""
    try:
        if "/run/systemd/resolve/" in os.path.realpath(LINUX_RESOLV_CONF):
            return True
        with open(LINUX_RESOLV_CONF, "r", encoding="utf-8") as f:
            return any(line.split()[1:2] in (["127.0.0.53"], ["127.0.0.54"]) for line in f if line.startswith("nameserver"))
    except OSError:
        return False


def _linux_dnsmasq_service_active() -> bool:
    return _run_systemctl("is-active", "dnsmasq")


def _linux_networkmanager_available() -> bool:
    if not shutil.which("nmcli"):
        return False
    r = _run(["nmcli", "-t", "-f", "RUNNING", "general"], timeout=5)
    return r is not None and r.returncode == 0 and r.stdout.strip() == "running"


def _linux_nm_dns_property(name: str) -> "str | None":
    """Read a NetworkManager DnsManager property (Mode or RcManager) as the running daemon
    sees it - e.g. Mode "default" (writes resolv.conf itself), "dnsmasq", "systemd-resolved",
    or "none"."""
    if shutil.which("busctl"):
        r = _run(
            [
                "busctl", "get-property", "org.freedesktop.NetworkManager",
                "/org/freedesktop/NetworkManager/DnsManager",
                "org.freedesktop.NetworkManager.DnsManager", name,
            ],
            timeout=5,
        )
        # Output looks like: s "dnsmasq"
        if r is not None and r.returncode == 0:
            m = re.match(r'^s\s+"([^"]*)"', r.stdout.strip())
            if m:
                return m.group(1)
    if name == "Mode" and shutil.which("NetworkManager"):
        r = _run(["NetworkManager", "--print-config"], timeout=5)
        if r is not None and r.returncode == 0:
            in_main = False
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith("["):
                    in_main = line == "[main]"
                elif in_main and line.startswith("dns="):
                    return line.split("=", 1)[1].strip()
            return "default"
    return None


def _linux_dnsmasq_binary_available() -> bool:
    return bool(shutil.which("dnsmasq")) or os.path.isfile("/usr/sbin/dnsmasq")


def _linux_resolv_conf_fallback_ok() -> bool:
    if not os.path.exists(LINUX_RESOLV_CONF):
        return False
    try:
        real = os.path.realpath(LINUX_RESOLV_CONF)
        if "/systemd/resolve/" in real or "/NetworkManager/" in real:
            return False
    except OSError:
        pass
    return True


def _linux_is_tun(ifname: str) -> bool:
    return os.path.exists(f"/sys/class/net/{ifname}/tun_flags")


def _linux_nebula_interface(tun_dev: str | None = None) -> str | None:
    """Return the Nebula interface name if it exists. With tun_dev (from the node's config),
    only that device counts - another ncclient's nebula on the same host must not match -
    and only if it is a tun device, so a config naming e.g. eth0 never gets DNS applied
    to the uplink. Without it (config from an older server), the first interface whose
    name contains "nebula"."""
    if tun_dev:
        return tun_dev if _linux_is_tun(tun_dev) else None
    r = _run(["ip", "-o", "link", "show"], timeout=5)
    if r is None or r.returncode != 0:
        return None
    for line in (r.stdout or "").strip().splitlines():
        parts = line.split(":", 2)
        if len(parts) >= 3 and "nebula" in parts[1].lower():
            return parts[1].strip().split("@", 1)[0]
    return None


def _linux_wait_for_nebula_interface(tun_dev: str | None = None, timeout: float = 10.0) -> str | None:
    """Nebula may still be creating its tun device right after a (re)start - wait briefly."""
    deadline = time.monotonic() + timeout
    while True:
        iface = _linux_nebula_interface(tun_dev)
        if iface or time.monotonic() >= deadline:
            return iface
        time.sleep(0.5)


def _linux_detect_backend() -> "tuple[str | None, str]":
    """Pick how this host's DNS is actually managed. Returns (backend, reason); backend is
    one of "resolved", "nm-dnsmasq", "dnsmasq", "resolv.conf", or None if split-horizon
    can't be done here (reason says why and what to install)."""
    if _linux_networkmanager_available():
        mode = _linux_nm_dns_property("Mode") or "default"
        rc_manager = _linux_nm_dns_property("RcManager") or ""
        if mode == "systemd-resolved":
            return "resolved", "NetworkManager delegates DNS to systemd-resolved"
        if mode == "dnsmasq":
            return "nm-dnsmasq", "NetworkManager runs its dnsmasq plugin"
        if mode != "none" and rc_manager != "unmanaged":
            if _linux_dnsmasq_binary_available():
                return "nm-dnsmasq", f"NetworkManager writes resolv.conf directly (dns={mode}); switching it to its dnsmasq plugin"
            if _linux_resolved_available() and _linux_resolv_conf_uses_resolved():
                return "resolved", "systemd-resolved owns resolv.conf"
            return None, (
                f"NetworkManager writes /etc/resolv.conf directly (dns={mode}), which can't route one domain "
                "to different servers. Install systemd-resolved or dnsmasq-base (NetworkManager's dnsmasq plugin) "
                "and restart ncclient."
            )
        # NetworkManager isn't handling DNS here - fall through to the other resolvers.
    if _linux_resolved_available():
        return "resolved", "systemd-resolved is running"
    if _linux_dnsmasq_service_active():
        return "dnsmasq", "a standalone dnsmasq service is running"
    if _linux_resolv_conf_fallback_ok():
        return "resolv.conf", "no local resolver found"
    return None, "no supported DNS resolver found (tried systemd-resolved, NetworkManager, dnsmasq, resolv.conf)"


# ---- NetworkManager housekeeping ----


def _linux_nm_reload(what: str) -> bool:
    """nmcli general reload conf|dns-full; falls back to a full NetworkManager reload (SIGHUP)."""
    r = _run(["nmcli", "general", "reload", what], timeout=15)
    if r is not None and r.returncode == 0:
        return True
    return _run_systemctl("reload", "NetworkManager")


def _linux_nm_keep_off_nebula() -> None:
    """Tell NetworkManager to leave the Nebula tun devices alone. Nebula creates and owns
    them; if NetworkManager ever takes one over (e.g. once its auto-generated "external"
    connection is modified and saved as a real profile), it brings the link down and nebula
    starts logging "Failed to write to tun: input/output error". Marking them unmanaged also
    stops NetworkManager from overwriting the per-link DNS the resolved backend sets.
    The content is the same for every instance (the server only hands out "nebula1" and
    "nc-*" names), so instances never rewrite each other's file."""
    changed = _write_if_changed(
        LINUX_NM_UNMANAGED_CONF,
        "# Written by ncclient (Nebula Commander): nebula owns its tun devices.\n"
        "[keyfile]\nunmanaged-devices=interface-name:nebula*;interface-name:nc-*\n",
    )
    if changed:
        _linux_nm_reload("conf")


def _linux_nm_remove_legacy_profiles() -> None:
    """Older ncclient versions ran `nmcli connection modify` on the Nebula device's
    auto-generated connection, which NetworkManager saved as a persistent tun profile under
    /etc/NetworkManager/system-connections/ - and which could take the tunnel down. Delete
    any such leftovers."""
    r = _run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,FILENAME", "connection", "show"], timeout=10)
    if r is None or r.returncode != 0:
        return
    for line in r.stdout.splitlines():
        # nmcli -t escapes ':' inside fields as '\:'
        fields = [f.replace("\\:", ":") for f in re.split(r"(?<!\\):", line)]
        if len(fields) < 4:
            continue
        name, uuid, conn_type, filename = fields[:4]
        if (
            conn_type == "tun"
            and name.lower().startswith("nebula")
            and filename.startswith("/etc/NetworkManager/system-connections/")
        ):
            _run(["nmcli", "connection", "delete", "uuid", uuid], timeout=10)
            print(f"Removed stale NetworkManager profile {name} ({uuid}) left by an older ncclient.", file=sys.stderr)


# ---- Backends ----


def _linux_resolved_apply(iface: str, domain: str, dns_servers: list[str]) -> bool:
    """Per-link DNS on the Nebula interface: only queries for ~domain go to its servers,
    everything else keeps using the host's normal DNS."""
    r = _run(["resolvectl", "dns", iface, *dns_servers])
    if r is None or r.returncode != 0:
        return False
    r = _run(["resolvectl", "domain", iface, f"~{domain}"])
    if r is None or r.returncode != 0:
        return False
    # Never use the Nebula DNS servers for anything outside ~domain (systemd >= 246).
    _run(["resolvectl", "default-route", iface, "false"])
    return _linux_resolved_verify(iface, domain, dns_servers)


def _linux_resolved_verify(iface: str, domain: str, dns_servers: list[str]) -> bool:
    r_dns = _run(["resolvectl", "dns", iface])
    r_dom = _run(["resolvectl", "domain", iface])
    if r_dns is None or r_dom is None or r_dns.returncode != 0 or r_dom.returncode != 0:
        return False
    servers = set(r_dns.stdout.split(":", 1)[-1].split())
    domains = r_dom.stdout.split(":", 1)[-1].split()
    return set(dns_servers) <= servers and f"~{domain}" in domains


def _linux_resolved_remove(tun_dev: str | None = None) -> None:
    iface = _linux_nebula_interface(tun_dev)
    if iface:
        _run(["resolvectl", "revert", iface])


def _instance_conf(legacy_path: str, tun_dev: str) -> str:
    """This instance's file next to legacy_path: .../nebula-commander-<tun_dev>.conf."""
    return os.path.join(os.path.dirname(legacy_path), f"nebula-commander-{tun_dev}.conf")


def _instance_confs_left(legacy_path: str) -> bool:
    """Whether any instance (or a pre-0.8.0 ncclient) still has a file next to legacy_path."""
    try:
        return any(
            name.startswith("nebula-commander") and name.endswith(".conf")
            for name in os.listdir(os.path.dirname(legacy_path))
        )
    except OSError:
        return False


def _file_has(path: str, content: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read() == content
    except OSError:
        return False


def _nm_dnsmasq_content(domain: str, dns_servers: list[str]) -> str:
    lines = [f"# Written by ncclient: split-horizon DNS for Nebula Commander domain {domain}"]
    lines += [f"server=/{domain}/{ip}" for ip in dns_servers]
    return "\n".join(lines) + "\n"


def _linux_nm_dnsmasq_apply(tun_dev: str, domain: str, dns_servers: list[str]) -> bool:
    """NetworkManager's dnsmasq plugin reads /etc/NetworkManager/dnsmasq.d/, so a server=
    line per Nebula DNS server routes just that domain to them. If NetworkManager isn't
    already in dnsmasq mode, switch it with a conf.d drop-in (removed again once no
    instance's file is left)."""
    try:
        conf_changed = _write_if_changed(
            _instance_conf(LINUX_NM_DNSMASQ_CONF, tun_dev), _nm_dnsmasq_content(domain, dns_servers)
        )
    except OSError:
        return False
    if _linux_nm_dns_property("Mode") != "dnsmasq":
        try:
            _write_if_changed(LINUX_NM_DNS_MODE_CONF, "# Written by ncclient (Nebula Commander).\n[main]\ndns=dnsmasq\n")
        except OSError:
            return False
        _linux_nm_reload("conf")
    elif conf_changed:
        _linux_nm_reload("dns-full")
    for _ in range(10):
        if _linux_nm_dnsmasq_verify(tun_dev, domain, dns_servers):
            return True
        time.sleep(0.5)
    return False


def _linux_nm_dnsmasq_verify(tun_dev: str, domain: str, dns_servers: list[str]) -> bool:
    return (
        _file_has(_instance_conf(LINUX_NM_DNSMASQ_CONF, tun_dev), _nm_dnsmasq_content(domain, dns_servers))
        and _linux_nm_dns_property("Mode") == "dnsmasq"
    )


def _linux_nm_dnsmasq_remove(tun_dev: str) -> None:
    """Remove this instance's file, and the dnsmasq mode drop-in once no instance needs it.
    Never LINUX_NM_UNMANAGED_CONF: reloading NetworkManager without it lets NetworkManager
    take over the tun device of every other instance still running."""
    removed_conf = _remove_file(_instance_conf(LINUX_NM_DNSMASQ_CONF, tun_dev))
    if tun_dev == LEGACY_TUN_DEV:
        removed_conf = _remove_file(LINUX_NM_DNSMASQ_CONF) or removed_conf
    removed_mode = not _instance_confs_left(LINUX_NM_DNSMASQ_CONF) and _remove_file(LINUX_NM_DNS_MODE_CONF)
    if not _linux_networkmanager_available():
        return
    if removed_mode:
        _linux_nm_reload("conf")
    elif removed_conf:
        _linux_nm_reload("dns-full")


def _dnsmasq_content(domain: str, dns_servers: list[str]) -> str:
    lines = [f"# Split-horizon for Nebula Commander domain {domain}"]
    lines += [f"server=/.{domain}/{ip}" for ip in dns_servers]
    return "\n".join(lines) + "\n"


def _linux_dnsmasq_restart() -> bool:
    if _run_systemctl("restart", "dnsmasq"):
        return True
    r = _run(["service", "dnsmasq", "restart"], timeout=15)
    return r is not None and r.returncode == 0


def _linux_dnsmasq_apply(tun_dev: str, domain: str, dns_servers: list[str]) -> bool:
    """Restarts dnsmasq only when this instance's file changed, so instances don't restart
    it for each other on every poll."""
    try:
        changed = _write_if_changed(_instance_conf(LINUX_DNSMASQ_CONF, tun_dev), _dnsmasq_content(domain, dns_servers))
    except OSError:
        return False
    return _linux_dnsmasq_restart() if changed else True


def _linux_dnsmasq_verify(tun_dev: str, domain: str, dns_servers: list[str]) -> bool:
    return _file_has(_instance_conf(LINUX_DNSMASQ_CONF, tun_dev), _dnsmasq_content(domain, dns_servers))


def _linux_dnsmasq_remove(tun_dev: str) -> None:
    removed = _remove_file(_instance_conf(LINUX_DNSMASQ_CONF, tun_dev))
    if tun_dev == LEGACY_TUN_DEV:
        removed = _remove_file(LINUX_DNSMASQ_CONF) or removed
    if removed:
        _linux_dnsmasq_restart()


def _linux_resolv_conf_apply(domain: str, dns_servers: list[str]) -> bool:
    try:
        content = ""
        if os.path.isfile(LINUX_RESOLV_CONF):
            with open(LINUX_RESOLV_CONF, "r", encoding="utf-8") as f:
                content = f.read()
        if RESOLV_MARKER in content:
            return True
        with open(LINUX_RESOLV_BACKUP, "w", encoding="utf-8") as f:
            f.write(content)
        block = f"\n{RESOLV_MARKER}\nsearch {domain}\n"
        for ip in dns_servers:
            block += f"nameserver {ip}\n"
        if not content.endswith("\n"):
            content += "\n"
        with open(LINUX_RESOLV_CONF, "w", encoding="utf-8") as f:
            f.write(content + block)
        return True
    except OSError:
        return False


def _linux_resolv_conf_verify() -> bool:
    try:
        with open(LINUX_RESOLV_CONF, "r", encoding="utf-8") as f:
            return RESOLV_MARKER in f.read()
    except OSError:
        return False


def _linux_resolv_conf_remove() -> None:
    try:
        if not os.path.isfile(LINUX_RESOLV_BACKUP):
            if os.path.isfile(LINUX_RESOLV_CONF):
                with open(LINUX_RESOLV_CONF, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if not any(RESOLV_MARKER in line for line in lines):
                    return
                out = []
                skip = False
                for line in lines:
                    if RESOLV_MARKER in line:
                        skip = True
                        continue
                    if skip and line.strip() and (line.strip().startswith("nameserver ") or line.strip().startswith("search ")):
                        continue
                    skip = False
                    out.append(line)
                with open(LINUX_RESOLV_CONF, "w", encoding="utf-8") as f:
                    f.writelines(out)
            return
        with open(LINUX_RESOLV_BACKUP, "r", encoding="utf-8") as f:
            content = f.read()
        with open(LINUX_RESOLV_CONF, "w", encoding="utf-8") as f:
            f.write(content)
        os.remove(LINUX_RESOLV_BACKUP)
    except OSError:
        pass


def _linux_remove_legacy_files() -> None:
    """Clean up what older ncclient versions wrote: a global resolved drop-in (sent every
    query, not just ~domain, to the Nebula DNS servers) and a systemd-networkd .network file.
    Only restarts a service if there was actually something to remove."""
    if _remove_file(LINUX_DROPIN):
        _run_systemctl("restart", "systemd-resolved")
    if _remove_file(LINUX_NETWORKD_NETWORK):
        _run_systemctl("restart", "systemd-networkd")


# What the last successful apply did, so ensure_split_horizon_dns() can check it's still in effect.
_linux_applied: "dict | None" = None


def _instance_tun_dev(tun_dev: str | None) -> str:
    """The device that names this instance's files. Without a config yet (tun_dev None),
    ncclient runs nebula on LEGACY_TUN_DEV, as ncclient before 0.8.0 always did."""
    return tun_dev or LEGACY_TUN_DEV


def _apply_linux(domain: str, dns_servers: list[str], tun_dev: str | None = None) -> bool:
    global _linux_applied
    _linux_applied = None
    _linux_remove_legacy_files()
    nm_running = _linux_networkmanager_available()
    if nm_running:
        _linux_nm_keep_off_nebula()
        _linux_nm_remove_legacy_profiles()
    instance = _instance_tun_dev(tun_dev)

    backend, reason = _linux_detect_backend()
    if backend is None:
        _report(f"Failed to apply split-horizon DNS: {reason}")
        return False

    ok = False
    iface = None
    if backend == "resolved":
        iface = _linux_wait_for_nebula_interface(tun_dev)
        if not iface:
            _report("Split-horizon DNS not applied yet: Nebula interface not found (will retry).")
            return False
        ok = _linux_resolved_apply(iface, domain, dns_servers)
    elif backend == "nm-dnsmasq":
        ok = _linux_nm_dnsmasq_apply(instance, domain, dns_servers)
    elif backend == "dnsmasq":
        ok = _linux_dnsmasq_apply(instance, domain, dns_servers)
    elif backend == "resolv.conf":
        ok = _linux_resolv_conf_apply(domain, dns_servers)

    if not ok:
        _report(f"Failed to apply split-horizon DNS via {backend} ({reason}).")
        return False
    _linux_applied = {
        "backend": backend,
        "iface": iface,
        "tun_dev": tun_dev,
        "domain": domain,
        "servers": list(dns_servers),
    }
    if backend == "resolv.conf":
        _report(
            "Split-horizon DNS applied via /etc/resolv.conf (limited; not true split-horizon, and "
            "only one ncclient per host can use it). Install systemd-resolved or dnsmasq for proper "
            "split-horizon DNS."
        )
    else:
        _report(f"Split-horizon DNS applied via {backend} ({reason}).")
    return True


def _linux_verify_applied() -> bool:
    a = _linux_applied
    if not a:
        return False
    backend = a["backend"]
    if backend == "resolved":
        iface = _linux_nebula_interface(a["iface"])
        return iface == a["iface"] and _linux_resolved_verify(iface, a["domain"], a["servers"])
    if backend == "nm-dnsmasq":
        return _linux_nm_dnsmasq_verify(_instance_tun_dev(a["tun_dev"]), a["domain"], a["servers"])
    if backend == "dnsmasq":
        return _linux_dnsmasq_verify(_instance_tun_dev(a["tun_dev"]), a["domain"], a["servers"])
    if backend == "resolv.conf":
        return _linux_resolv_conf_verify()
    return False


def _remove_linux(tun_dev: str | None = None) -> bool:
    global _linux_applied
    _linux_applied = None
    _linux_remove_legacy_files()
    _linux_resolved_remove(tun_dev)
    _linux_nm_dnsmasq_remove(_instance_tun_dev(tun_dev))
    _linux_dnsmasq_remove(_instance_tun_dev(tun_dev))
    _linux_resolv_conf_remove()
    return True


def _nrpt_rule_name(tun_dev: str | None) -> str:
    """One NRPT rule (DisplayName) per network, so removing one network's DNS leaves the
    others'. The legacy device keeps the pre-0.8.0 name, which a single-network install
    already has."""
    if not tun_dev or tun_dev == LEGACY_TUN_DEV:
        return NRPT_RULE_NAME
    return f"{NRPT_RULE_NAME}-{tun_dev}"


def _apply_windows(domain: str, dns_servers: list[str], tun_dev: str | None = None) -> bool:
    # NRPT: namespace with leading dot. Rule name per network for idempotent remove.
    if not dns_servers:
        return False
    rule_name = _nrpt_rule_name(tun_dev)
    namespace = f".{domain}" if not domain.startswith(".") else domain
    # PowerShell: -DisplayName (friendly name), -NameServers (DNS servers). -Name is not a valid Add parameter.
    # Remove each NebulaCommander rule by its .Name (GUID) so all old namespaces are cleared.
    # Remove via Remove-DnsClientNrptRule -Name (CIM delete doesn't work for NRPT).
    addrs = ",".join(f"'{s}'" for s in dns_servers)
    _remove_windows(tun_dev)
    ps_add = f"""
$ErrorActionPreference = 'Stop'
$ConfirmPreference = 'None'
Add-DnsClientNrptRule -Namespace '{namespace}' -DisplayName '{rule_name}' -NameServers @({addrs}) -Confirm:$false
"""
    try:
        subprocess.run(  # nosec B603 - fixed command resolved via shutil.which, shell=False
            [_which("powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", ps_add],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"Failed to apply NRPT: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr.decode(errors="replace"), file=sys.stderr)
        return False


def _remove_windows(tun_dev: str | None = None) -> bool:
    # Same loop as manual cleanup: Get-DnsClientNrptRule + Remove-DnsClientNrptRule -Name.
    # Run without -NonInteractive so Remove-DnsClientNrptRule doesn't hit "Read and Prompt" (fails when the calling process exits).
    ps = f"""
$ErrorActionPreference = 'Stop'
$ConfirmPreference = 'None'
$RuleName = '{_nrpt_rule_name(tun_dev)}'
$max = 10
for ($i = 0; $i -lt $max; $i++) {{
  $names = @(Get-DnsClientNrptRule | Where-Object {{ $_.DisplayName -eq $RuleName }} | ForEach-Object {{ $_.Name }})
  if ($names.Count -eq 0) {{ break }}
  foreach ($n in $names) {{ Remove-DnsClientNrptRule -Name $n -Confirm:$false -Force -ErrorAction SilentlyContinue }}
}}
"""
    try:
        subprocess.run(  # nosec B603 - fixed command resolved via shutil.which, shell=False
            [_which("powershell.exe"), "-NoProfile", "-Command", ps],  # no -NonInteractive
            check=True,
            capture_output=True,
            timeout=60,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"Failed to remove NRPT rule: {e}", file=sys.stderr)
        if getattr(e, "stderr", None):
            print(e.stderr.decode(errors="replace"), file=sys.stderr)
        return False
