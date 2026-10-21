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
so LAN traffic - including a LAN DNS resolver - goes through the exit node too.

Windows has no policy routing: Nebula keeps installing the route, and this module adds
/32 bypass routes via the physical default gateway for every underlay address in
static_host_map (lighthouses, relays, the exit gateway - which is why an exit node
needs a public endpoint for Windows consumers).

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
import socket
import subprocess  # nosec B404 - used with shell=False and validated/fixed args
import sys
import time
from dataclasses import dataclass, field
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
    underlay_ips: tuple[str, ...] = field(default_factory=tuple)  # static_host_map, IPv4


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

def _resolve_ipv4(host: str) -> list[str]:
    try:
        return [str(ipaddress.IPv4Address(host))]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    return sorted({info[4][0] for info in infos})


def _underlay_ipv4s(static_host_map: object) -> tuple[str, ...]:
    """IPv4 underlay addresses from static_host_map ("ip:port" / "host:port" / "[v6]:port")."""
    ips: set[str] = set()
    if not isinstance(static_host_map, dict):
        return ()
    for addrs in static_host_map.values():
        for addr in addrs if isinstance(addrs, list) else [addrs]:
            if not isinstance(addr, str) or addr.startswith("["):
                continue  # IPv6 underlay: blocked or routed natively, never bypassed
            host = addr.rsplit(":", 1)[0] if ":" in addr else addr
            ips.update(_resolve_ipv4(host.strip()))
    return tuple(sorted(ips, key=lambda ip: ipaddress.IPv4Address(ip)))


def plan_from_config(config_bytes: bytes, resolve: bool = True) -> Optional[ExitPlan]:
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
    try:
        port = int((parsed.get("listen") or {}).get("port", 4242))
    except (TypeError, ValueError):
        port = 4242
    underlay = _underlay_ipv4s(parsed.get("static_host_map")) if resolve else ()
    return ExitPlan(tun_dev=dev, listen_port=port, route_v6=EXIT_V6 in routes, underlay_ips=underlay)


# --- Linux -------------------------------------------------------------------------

def linux_commands(
    plan: ExitPlan,
    ports: list[int],
    allow_lan: bool,
    overlay_v4: list[str],
    overlay_v6: list[str],
    ipv6: bool = True,
    tun_present: bool = True,
) -> list[list[str]]:
    """The ip(8) argv lists that install the exit routing for plan (pure, for tests).
    ports: the UDP ports of every Nebula on the host - another network's nebula must not
    be routed into this exit tunnel either. ipv6=False (IPv6 disabled on the host) leaves
    out every -6 command; tun_present=False (Nebula's device not up yet) installs only
    the kill switch."""
    cmds: list[list[str]] = []
    families = [("-4", overlay_v4)] + ([("-6", overlay_v6)] if ipv6 else [])
    for fam, overlay in families:
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
            if fam == "-4":
                cmds.append(["ip", fam, "rule", "add", "pref", str(RULE_PREF_LOCAL),
                             "ipproto", "udp", "dport", "67", "lookup", "main"])  # DHCP renewals
        cmds.append(["ip", fam, "rule", "add", "pref", str(RULE_PREF_EXIT), "lookup", str(ROUTE_TABLE)])
    # Kill switch: an unreachable default under the real one, so while Nebula's device is
    # missing (starting, crashed) traffic is dropped instead of leaving outside the tunnel.
    # It's also the whole IPv6 table when the gateway can't route ::/0 (fails closed).
    for fam in [f for f, _ in families]:
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


_linux_applied: Optional[tuple] = None


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


def _linux_apply(plan: ExitPlan, allow_lan: bool, nebula_pid: Optional[int], debug_log) -> bool:
    global _linux_applied
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
    ipv6 = _linux_ipv6_enabled()
    key = (plan.tun_dev, tuple(ports), plan.route_v6, allow_lan, tuple(overlay_v4), tuple(overlay_v6), ipv6, tun_present)
    if key == _linux_applied and _linux_present(plan, tun_present):
        return True
    _linux_remove()
    for cmd in linux_commands(plan, ports, allow_lan, overlay_v4, overlay_v6, ipv6=ipv6, tun_present=tun_present):
        r = _run(cmd)
        if r is None or r.returncode != 0:
            # Any failure - IPv6 included, since a missing v6 block would leak - undoes the
            # whole set: a half-installed one could loop Nebula's own traffic.
            _log(f"Exit node: {' '.join(cmd)} failed: {((r.stderr if r else '') or 'not run').strip()}", debug_log)
            _linux_remove()
            return False
    _linux_applied = key
    _log(f"Exit node: all traffic routed via {plan.tun_dev}"
         # route_v6 only says the config routes ::/0: on an IPv4-only network the gateway's
         # cert can't carry it, and the gateway drops the IPv6 instead of forwarding it.
         f" ({'LAN allowed' if allow_lan else 'LAN blocked'}, IPv6 {'into the tunnel' if plan.route_v6 else 'blocked'})",
         debug_log)
    return True


# --- Windows -----------------------------------------------------------------------

def _powershell(script: str, timeout: float = 60) -> "subprocess.CompletedProcess | None":
    return _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


def _windows_default_gateway(tun_dev: str) -> Optional[tuple[int, str]]:
    """(ifIndex, next hop) of the best physical IPv4 default route, skipping Nebula's."""
    script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$r = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' |
  Where-Object {{ $_.InterfaceAlias -ne '{tun_dev}' -and $_.NextHop -ne '0.0.0.0' }} |
  Sort-Object {{ $_.RouteMetric + (Get-NetIPInterface -InterfaceIndex $_.ifIndex -AddressFamily IPv4).InterfaceMetric }} |
  Select-Object -First 1
if ($r) {{ "$($r.ifIndex) $($r.NextHop)" }}
"""
    r = _powershell(script)
    if r is None or r.returncode != 0:
        return None
    parts = (r.stdout or "").strip().split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), str(ipaddress.IPv4Address(parts[1]))
    except ValueError:
        return None


def windows_script(add: dict, remove: Optional[dict], tun_dev: str) -> str:
    """PowerShell that removes `remove`'s routes/rules and installs `add`'s (pure, for tests).
    Both are state dicts: {"if_index", "gateway", "routes": [ip...], "lan": cidr|None,
    "block_v6": bool}."""
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
        for ip in add.get("routes") or []:
            lines.append(
                f"New-NetRoute -DestinationPrefix '{ip}/32' -InterfaceIndex {int(add['if_index'])} "
                f"-NextHop '{add['gateway']}' -RouteMetric 1 -PolicyStore ActiveStore | Out-Null"
            )
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
        ips = ", ".join(f"'{ip}'" for ip in add.get("routes") or [])
        lines.append("$missing = 0")
        lines.append(
            f"foreach ($ip in @({ips})) {{ if (-not (Get-NetRoute -DestinationPrefix \"$ip/32\" "
            f"-InterfaceIndex {int(add['if_index'])} -PolicyStore ActiveStore)) {{ $missing++ }} }}"
        )
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
    gw = _windows_default_gateway(plan.tun_dev)
    if gw is None:
        _log("Exit node: no physical IPv4 default route found; bypass routes not applied", debug_log)
        return False
    if_index, gateway = gw
    desired = {
        "tun_dev": plan.tun_dev,
        "if_index": if_index,
        "gateway": gateway,
        "routes": list(plan.underlay_ips),
        "lan": None if allow_lan else _windows_lan_prefix(if_index),
        "block_v6": not plan.route_v6,
    }
    current = _windows_load(state_dir)
    # Re-asserted on every call even when unchanged: ActiveStore routes vanish when an
    # interface goes down, and New-NetRoute on an existing route is a silent no-op.
    r = _powershell(windows_script(desired, current if current != desired else None, plan.tun_dev))
    if r is None or "MISSING:0" not in (r.stdout or ""):
        found = re.search(r"MISSING:(\d+)", (r.stdout or "") if r else "")
        detail = f"{found.group(1)} bypass route(s) missing" if found else ((r.stderr if r else "") or "not run").strip()
        _log(f"Exit node: applying bypass routes failed: {detail}", debug_log)
        return False
    if current != desired:
        _windows_save(state_dir, desired)
        _log(f"Exit node: {len(plan.underlay_ips)} underlay address(es) bypass the tunnel via {gateway}", debug_log)
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
        plan = plan_from_config(config_bytes, resolve=sys.platform == "win32")
        if plan is None:
            # Only undo what this process (or, on Windows, the state file) says is there:
            # stale rules from a crash are cleared by the remove() at poll-loop start.
            if _linux_applied is not None or (sys.platform == "win32" and _windows_load(state_dir)):
                remove(state_dir, debug_log)
            return False
        if sys.platform.startswith("linux"):
            return _linux_apply(plan, allow_lan, nebula_pid, debug_log)
        if sys.platform == "win32":
            return _windows_apply(plan, allow_lan, state_dir, debug_log)
        return False
    except Exception as e:  # never take down the poll loop
        _log(f"Exit node: routing update failed: {type(e).__name__}: {e}", debug_log)
        return False


def remove(state_dir: str, debug_log: Optional[Callable[[str], None]] = None) -> None:
    """Undo everything apply() installed (exit node rejected, revoked, ncclient stopping)."""
    try:
        if sys.platform.startswith("linux"):
            _linux_remove()
        elif sys.platform == "win32":
            _windows_remove(state_dir, debug_log)
    except Exception as e:
        _log(f"Exit node: routing cleanup failed: {type(e).__name__}: {e}", debug_log)
