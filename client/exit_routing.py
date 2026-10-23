"""
Full-tunnel routing for a node that uses an exit node (consumer side).

Nebula installs a `tun.unsafe_routes` 0.0.0.0/0 entry as a plain `default dev <tun>`
route (metric 0) in the main table. Nebula's own encrypted UDP to the exit gateway,
lighthouses and peers is routed with that same table, so anything not on the local
LAN - a VPS exit node, a public lighthouse - gets routed into the tunnel it is supposed
to carry: the gateway, the peers and the internet all become unreachable, and so does
any other Nebula network on the host. Measured with network namespaces and Nebula
1.11.1 before this module existed; see docs/unsafe-routes.md.

Linux: ncclient writes the exit entries with `install: false` (see
ncclient.filter_accepted_routes), so Nebula keeps the route internally only, and this
module installs the full-tunnel default itself, policy-routed so that only Nebula's own
UDP (matched by its listen port) keeps using the normal route:

    pref 32740  ipproto udp sport <each nebula's port>  lookup main
    pref 32741  lookup main suppress_prefixlength 0  (LAN, overlay, bridges stay local)
    pref 32742  lookup 52042                       -> default dev <tun>
                                                      unreachable default (kill switch)

The unreachable default sits under the real one, so while Nebula's device is missing
(starting, crashed) internet traffic is dropped rather than leaking around the tunnel.

With exit_allow_lan off, 32741 only keeps the Nebula overlay subnets (and DHCP) local,
so LAN traffic - including a LAN DNS resolver - goes through the exit node too. Replies
to connections coming in from the LAN still go out directly: they're sent from the
host's own address (32741 `from <addr>`), which new outgoing connections never are when
they're routed.

Windows has no policy routing, so Nebula keeps installing the route and ncclient binds
Nebula's socket to the physical uplink's IPv4 address instead (listen.host, see
bind_to_uplink). Windows' strong host model sends a packet only out of the interface
that owns its source address, so Nebula's UDP stays on the uplink while everything
else - including other traffic to the gateway, lighthouses or the control server -
goes through the tunnel. /32 bypass routes, the first approach, had to exempt those
addresses entirely. The address is re-checked on every poll; when it changes (DHCP,
another Wi-Fi) the config is rewritten and Nebula restarted.

IPv6 fails closed: when the exit gateway doesn't route ::/0 (its cert can only carry
::/0 on a dual-stack network), IPv6 is blocked instead of leaving outside the tunnel -
an `unreachable` default in table 52042 on Linux, an outbound firewall block on
Windows.

Never raises: a routing failure is logged, not allowed to take down the poll loop.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess  # nosec B404 - used with shell=False and validated/fixed args
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional

EXIT_V4 = "0.0.0.0/0"
EXIT_V6 = "::/0"

# Must sort before the kernel's own `from all lookup main` (32766), or main's default
# route answers first; clear of wg-quick (32764/32765) and Tailscale (5210-5270).
RULE_PREF_NEBULA = 32740
RULE_PREF_LOCAL = 32741
RULE_PREF_EXIT = 32742
ROUTE_TABLE = 52042
KILL_SWITCH_METRIC = 2147483647
_RULE_PREFS = (RULE_PREF_NEBULA, RULE_PREF_LOCAL, RULE_PREF_EXIT)

WINDOWS_STATE_FILE = "exit-bypass.json"
WINDOWS_V6_BLOCK_RULE = "NebulaCommander exit node IPv6 block"

_SYSTEM_LIBRARY_ENV_STRIP = ("LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT", "LIBPATH")
# Interface names and addresses end up in argv / PowerShell source: interface-name or
# IP shaped only.
_IFNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,15}$")


@dataclass(frozen=True)
class ExitPlan:
    """What the node's config.yaml asks for, independent of the host's state."""

    tun_dev: str
    listen_port: int
    route_v6: bool  # the exit gateway routes ::/0 too
    listen_host: str = "0.0.0.0"


def _which(name: str) -> str:
    return shutil.which(name) or name


def _env_for_system_binaries() -> dict:
    env = os.environ.copy()
    for key in _SYSTEM_LIBRARY_ENV_STRIP:
        env.pop(key, None)
    return env


def _log(msg: str, debug_log: Optional[Callable[[str], None]] = None) -> None:
    if debug_log:
        debug_log(msg)
    else:
        print(msg, file=sys.stderr)


def _run(cmd: list[str], timeout: float = 10, input_text: Optional[str] = None) -> "subprocess.CompletedProcess | None":
    try:
        return subprocess.run(  # nosec B603 - fixed command resolved via shutil.which, shell=False
            [_which(cmd[0]), *cmd[1:]],
            input=input_text,
            capture_output=True,
            timeout=timeout,
            text=True,
            env=_env_for_system_binaries(),
        )
    except (subprocess.SubprocessError, OSError):
        return None


# --- config -> plan ----------------------------------------------------------------

def plan_from_config(config_bytes: bytes) -> Optional[ExitPlan]:
    """ExitPlan for a written config.yaml, or None when it has no exit route."""
    import yaml

    try:
        parsed = yaml.safe_load(config_bytes) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    tun = parsed.get("tun") or {}
    routes = {str((e or {}).get("route") or "").strip() for e in (tun.get("unsafe_routes") or []) if isinstance(e, dict)}
    if EXIT_V4 not in routes and EXIT_V6 not in routes:
        return None
    dev = tun.get("dev") or "nebula1"
    if not isinstance(dev, str) or not _IFNAME_RE.match(dev):
        return None
    listen = parsed.get("listen") or {}
    try:
        port = int(listen.get("port", 4242))
    except (TypeError, ValueError):
        port = 4242
    host = str(listen.get("host") or "0.0.0.0")
    return ExitPlan(tun_dev=dev, listen_port=port, route_v6=EXIT_V6 in routes, listen_host=host)


def with_listen_host(config_bytes: bytes, host: str) -> bytes:
    """config_bytes with listen.host set to host (unchanged bytes if it already is)."""
    import yaml

    parsed = yaml.safe_load(config_bytes) or {}
    if not isinstance(parsed, dict):
        return config_bytes
    listen = parsed.get("listen") or {}
    if str(listen.get("host") or "0.0.0.0") == host:
        return config_bytes
    parsed["listen"] = {**listen, "host": host}
    return yaml.dump(parsed, default_flow_style=False, sort_keys=False, allow_unicode=True).encode("utf-8")


# --- Linux -------------------------------------------------------------------------

def linux_commands(
    plan: ExitPlan,
    ports: list[int],
    allow_lan: bool,
    overlay_v4: list[str],
    overlay_v6: list[str],
    ipv6: bool = True,
    tun_present: bool = True,
    local_v4: tuple[str, ...] = (),
    local_v6: tuple[str, ...] = (),
) -> list[list[str]]:
    """The ip(8) argv lists that install the exit routing for plan (pure, for tests).
    ports: the UDP ports of every Nebula on the host - another network's nebula must not
    be routed into this exit tunnel either. ipv6=False (IPv6 disabled on the host) leaves
    out every -6 command; tun_present=False (Nebula's device not up yet) installs only
    the kill switch. local_v4/local_v6: the host's own non-tunnel addresses, for the
    LAN-blocked mode's reply rule."""
    cmds: list[list[str]] = []
    families = [("-4", overlay_v4, local_v4)] + ([("-6", overlay_v6, local_v6)] if ipv6 else [])
    for fam, overlay, own_addrs in families:
        # Nebula's own UDP keeps the normal routes - first, so nothing below can catch it.
        for port in ports:
            cmds.append(["ip", fam, "rule", "add", "pref", str(RULE_PREF_NEBULA),
                         "ipproto", "udp", "sport", str(port), "lookup", "main"])
        if allow_lan:
            cmds.append(["ip", fam, "rule", "add", "pref", str(RULE_PREF_LOCAL),
                         "lookup", "main", "suppress_prefixlength", "0"])
        else:
            local = list(overlay)
            if fam == "-6":
                local += ["fe80::/10", "ff00::/8"]  # neighbour discovery and multicast
            for cidr in local:
                cmds.append(["ip", fam, "rule", "add", "pref", str(RULE_PREF_LOCAL),
                             "to", cidr, "lookup", "main"])
            # Replies to connections that came in from the LAN (SSH, a file share, a web
            # UI) are sent from the address the connection arrived on; a new outgoing
            # connection has no source address yet when routed, so this doesn't let it
            # around the exit node. Without it, blocking LAN access cut off every inbound
            # connection from the LAN (measured: SSH into a Debian VM dropped).
            for addr in own_addrs:
                cmds.append(["ip", fam, "rule", "add", "pref", str(RULE_PREF_LOCAL),
                             "from", addr, "lookup", "main"])
            if fam == "-4":
                cmds.append(["ip", fam, "rule", "add", "pref", str(RULE_PREF_LOCAL),
                             "ipproto", "udp", "dport", "67", "lookup", "main"])  # DHCP renewals
        cmds.append(["ip", fam, "rule", "add", "pref", str(RULE_PREF_EXIT), "lookup", str(ROUTE_TABLE)])
    # Kill switch: an unreachable default under the real one, so while Nebula's device is
    # missing (starting, crashed) traffic is dropped instead of leaving outside the tunnel.
    # It's also the whole IPv6 table when the gateway can't route ::/0 (fails closed).
    for fam in [f for f, _, _ in families]:
        cmds.append(["ip", fam, "route", "replace", "unreachable", "default",
                     "metric", str(KILL_SWITCH_METRIC), "table", str(ROUTE_TABLE)])
    if tun_present:
        cmds.append(["ip", "-4", "route", "replace", "default", "dev", plan.tun_dev, "table", str(ROUTE_TABLE)])
        if ipv6 and plan.route_v6:
            cmds.append(["ip", "-6", "route", "replace", "default", "dev", plan.tun_dev, "table", str(ROUTE_TABLE)])
    return cmds


def _linux_ipv6_enabled() -> bool:
    try:
        with open("/proc/sys/net/ipv6/conf/all/disable_ipv6", "r", encoding="ascii") as f:
            return f.read().strip() != "1"
    except OSError:
        return False  # no IPv6 stack at all


def _linux_nebula_ports(nebula_pid: Optional[int]) -> list[int]:
    """UDP ports bound by every nebula process on the host (this node's, found by pid
    for listen.port 0, and any other network's), from ss(8)."""
    r = _run(["ss", "-Hulpn"])
    if r is None or r.returncode != 0:
        return []
    ports: set[int] = set()
    for line in (r.stdout or "").splitlines():
        if '(("nebula",' not in line and not (nebula_pid and f"pid={nebula_pid}," in line):
            continue
        # "UNCONN 0 0 0.0.0.0:4242 0.0.0.0:* users:((...))" / "[::]:4242 [::]:*"
        m = re.search(r":(\d+)\s+\S*:\*", line)
        if m:
            ports.add(int(m.group(1)))
    return sorted(ports)


def _linux_tun_networks() -> tuple[list[str], list[str]]:
    """Networks on every tun device on the host (all Nebula overlays, for strict mode)."""
    v4: set[str] = set()
    v6: set[str] = set()
    try:
        names = os.listdir("/sys/class/net")
    except OSError:
        return [], []
    for name in names:
        if not os.path.exists(f"/sys/class/net/{name}/tun_flags"):
            continue
        r = _run(["ip", "-o", "addr", "show", "dev", name])
        if r is None or r.returncode != 0:
            continue
        for m in re.finditer(r"\binet6? (\S+)", r.stdout or ""):
            try:
                net = ipaddress.ip_interface(m.group(1)).network
            except ValueError:
                continue
            if net.version == 4:
                v4.add(str(net))
            elif not net.is_link_local:
                v6.add(str(net))
    return sorted(v4), sorted(v6)


def _linux_own_addresses() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The host's own addresses outside every tunnel (IPv4, global IPv6): the sources of
    its replies to LAN clients. Loopback and tun devices (Nebula, other VPNs) excluded."""
    r = _run(["ip", "-o", "addr", "show"])
    if r is None or r.returncode != 0:
        return (), ()
    v4: set[str] = set()
    v6: set[str] = set()
    for line in (r.stdout or "").splitlines():
        m = re.match(r"\d+:\s+(\S+?)(?:@\S+)?\s+(inet6?)\s+(\S+)", line)
        if not m:
            continue
        ifname, family, cidr = m.groups()
        if ifname == "lo" or os.path.exists(f"/sys/class/net/{ifname}/tun_flags"):
            continue
        try:
            addr = ipaddress.ip_interface(cidr).ip
        except ValueError:
            continue
        if addr.version == 4:
            v4.add(str(addr))
        elif not (addr.is_link_local or addr.is_loopback):
            v6.add(str(addr))
    return tuple(sorted(v4)), tuple(sorted(v6))


_linux_applied: Optional[tuple] = None

# The rules and table 52042 are host-wide, while each ncclient process (the packaged
# service, a Docker container, a second `ncclient run`) only knows its own state. The
# process that installed them records itself here so the others leave them alone - a
# second process's start-up clean-up would otherwise drop the first one's kill switch.
LINUX_OWNER_FILE = "/run/ncclient/exit-owner.json"


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _linux_owner() -> Optional[dict]:
    try:
        with open(LINUX_OWNER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _linux_other_owner(state_dir: str) -> Optional[dict]:
    """The owner record if a different, still running ncclient installed the rules."""
    owner = _linux_owner()
    if not owner or owner.get("state_dir") == os.path.abspath(state_dir):
        return None
    return owner if _pid_alive(owner.get("pid")) else None


def _linux_set_owner(state_dir: str) -> None:
    try:
        os.makedirs(os.path.dirname(LINUX_OWNER_FILE), mode=0o755, exist_ok=True)
        tmp = LINUX_OWNER_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"state_dir": os.path.abspath(state_dir), "pid": os.getpid()}, f)
        os.replace(tmp, LINUX_OWNER_FILE)
    except OSError:
        pass  # without the record a second instance may clean up too eagerly - not fatal


def _linux_clear_owner() -> None:
    try:
        os.remove(LINUX_OWNER_FILE)
    except OSError:
        pass


def _linux_present(plan: ExitPlan, tun_present: bool) -> bool:
    r = _run(["ip", "-4", "route", "show", "table", str(ROUTE_TABLE)])
    routes = (r.stdout or "") if r is not None else ""
    if "unreachable default" not in routes or (tun_present and f"dev {plan.tun_dev}" not in routes):
        return False
    rules = _run(["ip", "-4", "rule", "show", "pref", str(RULE_PREF_NEBULA)])
    return rules is not None and bool((rules.stdout or "").strip())


def _linux_remove() -> None:
    global _linux_applied
    _linux_applied = None
    for fam in ("-4", "-6"):
        for pref in _RULE_PREFS:
            for _ in range(64):  # strict mode can have several rules per pref
                r = _run(["ip", fam, "rule", "del", "pref", str(pref)])
                if r is None or r.returncode != 0:
                    break
        _run(["ip", fam, "route", "flush", "table", str(ROUTE_TABLE)])


def _linux_apply(plan: ExitPlan, allow_lan: bool, nebula_pid: Optional[int], debug_log, state_dir: str = "") -> bool:
    global _linux_applied
    other = _linux_other_owner(state_dir)
    if other:
        _log(f"Exit node: another ncclient on this host (pid {other.get('pid')}, {other.get('state_dir')}) "
             "already routes all traffic through an exit node; not applied", debug_log)
        return False
    # Nebula may still be creating its device right after a (re)start - wait briefly. If
    # it's still missing, only the kill switch goes in and the next call adds the route.
    tun_present = False
    for _ in range(20):
        if os.path.isdir(f"/sys/class/net/{plan.tun_dev}"):
            tun_present = True
            break
        if not nebula_pid:
            break
        time.sleep(0.5)
    # Re-read on every call, so a nebula another network starts later gets exempted too.
    ports = sorted(set(_linux_nebula_ports(nebula_pid)) | ({plan.listen_port} if plan.listen_port else set()))
    if not ports:
        _log("Exit node: could not find Nebula's UDP port (listen.port 0); exit routing not applied", debug_log)
        _linux_remove()
        return False
    overlay_v4, overlay_v6 = ([], []) if allow_lan else _linux_tun_networks()
    local_v4, local_v6 = ((), ()) if allow_lan else _linux_own_addresses()
    ipv6 = _linux_ipv6_enabled()
    key = (plan.tun_dev, tuple(ports), plan.route_v6, allow_lan, tuple(overlay_v4), tuple(overlay_v6), ipv6, tun_present,
           local_v4, local_v6)
    if key == _linux_applied and _linux_present(plan, tun_present):
        return True
    _linux_remove()
    for cmd in linux_commands(plan, ports, allow_lan, overlay_v4, overlay_v6, ipv6=ipv6, tun_present=tun_present,
                              local_v4=local_v4, local_v6=local_v6):
        r = _run(cmd)
        if r is None or r.returncode != 0:
            # Any failure - IPv6 included, since a missing v6 block would leak - undoes the
            # whole set: a half-installed one could loop Nebula's own traffic.
            _log(f"Exit node: {' '.join(cmd)} failed: {((r.stderr if r else '') or 'not run').strip()}", debug_log)
            _linux_remove()
            return False
    _linux_applied = key
    _linux_set_owner(state_dir)
    _log(f"Exit node: all traffic routed via {plan.tun_dev}"
         # route_v6 only says the config routes ::/0: on an IPv4-only network the gateway's
         # cert can't carry it, and the gateway drops the IPv6 instead of forwarding it.
         f" ({'LAN allowed' if allow_lan else 'LAN blocked'}, IPv6 {'into the tunnel' if plan.route_v6 else 'blocked'})",
         debug_log)
    return True


# --- Windows -----------------------------------------------------------------------

def _powershell(script: str, timeout: float = 60) -> "subprocess.CompletedProcess | None":
    return _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


def _windows_uplink(tun_dev: str) -> Optional[tuple[int, str]]:
    """(ifIndex, IPv4 address) of the interface carrying the best physical IPv4 default
    route, skipping Nebula's own."""
    script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$r = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' |
  Where-Object {{ $_.InterfaceAlias -ne '{tun_dev}' -and $_.NextHop -ne '0.0.0.0' }} |
  Sort-Object {{ $_.RouteMetric + (Get-NetIPInterface -InterfaceIndex $_.ifIndex -AddressFamily IPv4).InterfaceMetric }} |
  Select-Object -First 1
if ($r) {{
  $a = Get-NetIPAddress -InterfaceIndex $r.ifIndex -AddressFamily IPv4 |
    Where-Object {{ $_.AddressState -eq 'Preferred' }} | Select-Object -First 1
  if ($a) {{ "$($r.ifIndex) $($a.IPAddress)" }}
}}
"""
    r = _powershell(script)
    if r is None:
        return None
    parts = (r.stdout or "").strip().split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), str(ipaddress.IPv4Address(parts[1]))
    except ValueError:
        return None


def windows_uplink_ip(tun_dev: str = "nebula1") -> Optional[str]:
    """IPv4 address of the physical uplink, for listen.host (None if offline / not Windows)."""
    if sys.platform != "win32":
        return None
    uplink = _windows_uplink(tun_dev)
    return uplink[1] if uplink else None


def bind_to_uplink(config_bytes: bytes, debug_log: Optional[Callable[[str], None]] = None, force: bool = False) -> bytes:
    """Windows with an exit route: config_bytes with listen.host = the uplink's address, so
    Nebula's own UDP keeps leaving through the uplink (strong host model) while the exit
    route carries everything else. Unchanged on other platforms, without an exit route,
    or while no uplink is found (the next poll retries).
    force: another network on this host uses an exit node. Its default route captures
    every Nebula's UDP, so this one is bound to the uplink too."""
    if sys.platform != "win32":
        return config_bytes
    try:
        plan = plan_from_config(config_bytes)
        if plan is None and not force:
            # No exit route (any more): back to the server's 0.0.0.0, so a binding left over
            # from an exit node can't go stale when the address changes later.
            return with_listen_host(config_bytes, "0.0.0.0")
        if plan is not None:
            tun_dev = plan.tun_dev
        else:
            import yaml
            parsed = yaml.safe_load(config_bytes) or {}
            tun_dev = str(((parsed.get("tun") or {}) if isinstance(parsed, dict) else {}).get("dev") or "nebula1")
        ip = windows_uplink_ip(tun_dev)
        if not ip:
            _log("Exit node: no physical IPv4 uplink found yet; Nebula not bound to it", debug_log)
            return config_bytes
        return with_listen_host(config_bytes, ip)
    except Exception as e:  # never take down the poll loop
        _log(f"Exit node: binding Nebula to the uplink failed: {type(e).__name__}: {e}", debug_log)
        return config_bytes


def windows_script(add: dict, remove: Optional[dict], tun_dev: str) -> str:
    """PowerShell that removes `remove`'s routes/rules and installs `add`'s (pure, for tests).
    Both are state dicts: {"if_index", "lan": cidr|None, "block_v6": bool}. A state from
    the /32-bypass build may also carry "gateway" and "routes" - removed, never added."""
    lines = ["$ErrorActionPreference = 'SilentlyContinue'", "$ConfirmPreference = 'None'"]
    if remove:
        for ip in remove.get("routes") or []:
            lines.append(
                f"Remove-NetRoute -DestinationPrefix '{ip}/32' -InterfaceIndex {int(remove['if_index'])} "
                f"-NextHop '{remove['gateway']}' -PolicyStore ActiveStore -Confirm:$false"
            )
        if remove.get("lan"):
            lines.append(
                f"Remove-NetRoute -DestinationPrefix '{remove['lan']}' -InterfaceAlias '{tun_dev}' "
                f"-PolicyStore ActiveStore -Confirm:$false"
            )
        if remove.get("block_v6"):
            lines.append(f"Remove-NetFirewallRule -DisplayName '{WINDOWS_V6_BLOCK_RULE}'")
    if add:
        if add.get("lan"):
            lines.append(
                f"New-NetRoute -DestinationPrefix '{add['lan']}' -InterfaceAlias '{tun_dev}' "
                f"-RouteMetric 0 -PolicyStore ActiveStore | Out-Null"
            )
        if add.get("block_v6"):
            lines.append(
                f"if (-not (Get-NetFirewallRule -DisplayName '{WINDOWS_V6_BLOCK_RULE}')) {{ "
                f"New-NetFirewallRule -DisplayName '{WINDOWS_V6_BLOCK_RULE}' -Direction Outbound -Action Block "
                f"-RemoteAddress '2000::/3' -Profile Any | Out-Null }}"
            )
        # Judge by what's actually there: New-NetRoute on a route that already exists (the
        # per-poll re-assert) fails harmlessly, and powershell -Command exits 1 whenever
        # its last cmdlet failed, even under SilentlyContinue.
        lines.append("$missing = 0")
        if add.get("lan"):
            lines.append(
                f"if (-not (Get-NetRoute -DestinationPrefix '{add['lan']}' -InterfaceAlias '{tun_dev}' "
                f"-PolicyStore ActiveStore)) {{ $missing++ }}"
            )
        if add.get("block_v6"):
            lines.append(f"if (-not (Get-NetFirewallRule -DisplayName '{WINDOWS_V6_BLOCK_RULE}')) {{ $missing++ }}")
        lines.append('"MISSING:$missing"')
    lines.append("exit 0")
    return "\n".join(lines) + "\n"


def _windows_lan_prefix(if_index: int) -> Optional[str]:
    r = _powershell(
        f"$a = Get-NetIPAddress -InterfaceIndex {int(if_index)} -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
        f"Select-Object -First 1; if ($a) {{ \"$($a.IPAddress)/$($a.PrefixLength)\" }}"
    )
    if r is None or r.returncode != 0:
        return None
    try:
        return str(ipaddress.ip_interface((r.stdout or "").strip()).network)
    except ValueError:
        return None


def _windows_state_path(state_dir: str) -> str:
    return os.path.join(state_dir, WINDOWS_STATE_FILE)


def _windows_load(state_dir: str) -> Optional[dict]:
    try:
        with open(_windows_state_path(state_dir), "r", encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else None
    except (OSError, ValueError):
        return None


def _windows_save(state_dir: str, state: Optional[dict]) -> None:
    path = _windows_state_path(state_dir)
    try:
        if state is None:
            os.remove(path)
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass


def _windows_apply(plan: ExitPlan, allow_lan: bool, state_dir: str, debug_log) -> bool:
    uplink = _windows_uplink(plan.tun_dev)
    if uplink is None:
        _log("Exit node: no physical IPv4 uplink found", debug_log)
        return False
    if_index, ip = uplink
    if plan.listen_host != ip:
        # The poll loop rebinds (bind_to_uplink) and restarts Nebula; until then Nebula's
        # own UDP would follow the exit route into the tunnel.
        _log(f"Exit node: Nebula is bound to {plan.listen_host}, not the uplink {ip} yet", debug_log)
        return False
    desired = {
        "tun_dev": plan.tun_dev,
        "if_index": if_index,
        "lan": None if allow_lan else _windows_lan_prefix(if_index),
        "block_v6": not plan.route_v6,
    }
    current = _windows_load(state_dir)
    # Re-asserted on every call even when unchanged: ActiveStore routes vanish when an
    # interface goes down, and New-NetRoute on an existing route is a silent no-op.
    r = _powershell(windows_script(desired, current if current != desired else None, plan.tun_dev))
    if r is None or "MISSING:0" not in (r.stdout or ""):
        found = re.search(r"MISSING:(\d+)", (r.stdout or "") if r else "")
        detail = f"{found.group(1)} route/rule(s) missing" if found else ((r.stderr if r else "") or "not run").strip()
        _log(f"Exit node: applying routing failed: {detail}", debug_log)
        return False
    if current != desired:
        _windows_save(state_dir, desired)
        _log(f"Exit node: all traffic routed via {plan.tun_dev}, Nebula bound to the uplink {ip}"
             f" ({'LAN allowed' if allow_lan else 'LAN blocked'}, IPv6 {'into the tunnel' if plan.route_v6 else 'blocked'})",
             debug_log)
    return True


def _windows_remove(state_dir: str, debug_log) -> None:
    current = _windows_load(state_dir)
    if not current:
        return
    r = _powershell(windows_script({}, current, current.get("tun_dev") or "nebula1"))
    if r is None or r.returncode != 0:
        _log("Exit node: removing bypass routes failed", debug_log)
    _windows_save(state_dir, None)


# --- public API ----------------------------------------------------------------------

def apply(
    config_bytes: bytes,
    state_dir: str,
    allow_lan: bool = True,
    nebula_pid: Optional[int] = None,
    debug_log: Optional[Callable[[str], None]] = None,
) -> bool:
    """Make the host match config_bytes: full-tunnel exit routing when the config has an
    exit route, nothing otherwise. Idempotent and cheap when nothing changed - call it
    after every config write and on every unchanged poll (Nebula may have recreated its
    device, a laptop may have changed networks). Returns True when exit routing is in
    effect."""
    try:
        plan = plan_from_config(config_bytes)
        if plan is None:
            # Only undo what this process (or, on Windows, the state file) says is there:
            # stale rules from a crash are cleared by the remove() at poll-loop start.
            if _linux_applied is not None or (sys.platform == "win32" and _windows_load(state_dir)):
                remove(state_dir, debug_log)
            return False
        if sys.platform.startswith("linux"):
            return _linux_apply(plan, allow_lan, nebula_pid, debug_log, state_dir)
        if sys.platform == "win32":
            return _windows_apply(plan, allow_lan, state_dir, debug_log)
        return False
    except Exception as e:  # never take down the poll loop
        _log(f"Exit node: routing update failed: {type(e).__name__}: {e}", debug_log)
        return False


def remove(state_dir: str, debug_log: Optional[Callable[[str], None]] = None) -> None:
    """Undo everything apply() installed (exit node rejected, revoked, ncclient stopping).
    On Linux, rules another running ncclient installed are left alone."""
    try:
        if sys.platform.startswith("linux"):
            other = _linux_other_owner(state_dir)
            if other:
                _log(f"Exit node: rules belong to another ncclient (pid {other.get('pid')}); left in place", debug_log)
                return
            _linux_remove()
            _linux_clear_owner()
        elif sys.platform == "win32":
            _windows_remove(state_dir, debug_log)
    except Exception as e:
        _log(f"Exit node: routing cleanup failed: {type(e).__name__}: {e}", debug_log)
