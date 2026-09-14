"""
Linux-only subnet-router / exit-node support for ncclient.

Nebula's own `unsafe_routes` config only tells its tun driver to route a CIDR into the
overlay - it does not touch the host's IP forwarding or NAT, which is what actually makes
a node act as a gateway (the same gap `tailscaled` fills for `--advertise-routes` /
`--advertise-exit-node`). This module does two things:

  - discover_available_subnets(): enumerate local interfaces so the backend/UI can offer
    "advertise this subnet" choices (reported on heartbeat - see ncclient.py).
  - apply_routes(): given the node's current unsafe_routes and tun device, flip
    ip_forward and (re)install a dedicated nftables table that does the forwarding/NAT.

Linux only. Imported lazily by ncclient.py behind `sys.platform.startswith("linux")` so
it is never touched on Windows.

Caveat worth knowing if this ever runs on a NixRTR router host: nftables has no "any
table accepts, so it passes" rule - if another table's chain at the same hook (e.g. a
router firewall's own `forward` chain, such as nixos-router/modules/router.nix) has a
drop policy or an explicit drop, this module's accept rules in NFT_TABLE do not override
it. The two would need to be reconciled manually in that scenario; nothing here attempts
to detect or fix that.
"""
import ipaddress
import os
import re
import shutil
import subprocess  # nosec B404 - used with shell=False and validated/fixed args
import sys
from typing import Callable, Optional

_SYSTEM_LIBRARY_ENV_STRIP = ("LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT", "LIBPATH")

NFT_TABLE = "ncclient_routing"
EXIT_ROUTES = ("0.0.0.0/0", "::/0")

_DOCKER_PREFIXES = ("docker", "br-", "veth", "virbr")
_ETHERNET_PREFIXES = ("en", "eth")
_WIFI_PREFIXES = ("wl",)
_NEBULA_PREFIXES = ("nebula",)


def _which(name: str) -> str:
    """Resolve a system binary to an absolute path before spawning it, so we don't rely
    on subprocess's own PATH search (falls back to the bare name if not found)."""
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


# --- Subnet discovery -------------------------------------------------------------

def _is_docker_owned(ifname: str) -> bool:
    if ifname.startswith(_DOCKER_PREFIXES):
        return True
    return os.path.isdir(f"/sys/class/net/{ifname}/bridge")


def _classify(ifname: str) -> Optional[str]:
    """Best-effort interface classification; refine as real-world interface names
    surface (same "harden as deployments surface edge cases" approach the rest of the
    client takes - see README.md)."""
    if ifname == "lo":
        return None
    if _is_docker_owned(ifname):
        return None
    if ifname == "tailscale0":
        return "tailscale"
    if ifname.startswith(_NEBULA_PREFIXES):
        return "nebula"
    if os.path.isdir(f"/sys/class/net/{ifname}/wireless") or ifname.startswith(_WIFI_PREFIXES):
        return "wifi"
    if os.path.isdir(f"/sys/class/net/{ifname}/device") or ifname.startswith(_ETHERNET_PREFIXES):
        return "ethernet"
    return None


def _iface_ipv4_cidr(ifname: str) -> Optional[str]:
    """First non-link-local IPv4 network on this interface, or None."""
    try:
        r = subprocess.run(  # nosec B603 - fixed argv, ifname comes from /sys/class/net listing
            [_which("ip"), "-o", "-4", "addr", "show", "dev", ifname],
            capture_output=True,
            timeout=5,
            text=True,
            env=_env_for_system_binaries(),
        )
        if r.returncode != 0:
            return None
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", r.stdout or "")
        if not m:
            return None
        return str(ipaddress.ip_interface(m.group(1)).network)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def discover_available_subnets(own_tun_dev: Optional[str] = None) -> list[dict]:
    """
    Enumerate host interfaces for CIDRs an admin might want to advertise as a subnet
    route. Best-effort and never raises - this only feeds an optional UI affordance
    (reported on heartbeat), never something the poll loop should die over on a host
    with unusual networking.

    own_tun_dev: this node's own Nebula tun device name (from its config's `tun.dev`),
    excluded so a node never offers to advertise its own overlay interface. Other
    nebula*-named interfaces (a different ncclient/network on the same host) are still
    included as kind="nebula".
    """
    subnets: list[dict] = []
    try:
        ifnames = sorted(os.listdir("/sys/class/net"))
    except OSError:
        return subnets
    for ifname in ifnames:
        if own_tun_dev and ifname == own_tun_dev:
            continue
        kind = _classify(ifname)
        if not kind:
            continue
        cidr = _iface_ipv4_cidr(ifname)
        if not cidr:
            continue
        subnets.append({"interface": ifname, "cidr": cidr, "kind": kind})
    return subnets


# --- Host routing (ip_forward + nftables) -----------------------------------------

def _set_ip_forward(routes: list[dict]) -> None:
    """One-way enable only - never written back to 0. This runs on router-flavored
    hosts where forwarding may be wanted for other reasons; ncclient only ever adds
    host config it doesn't already own, it doesn't revert state on the way out."""
    try:
        with open("/proc/sys/net/ipv4/ip_forward", "w", encoding="ascii") as f:
            f.write("1\n")
    except OSError:
        pass
    if any(":" in (r.get("route") or "") for r in routes):
        try:
            with open("/proc/sys/net/ipv6/conf/all/forwarding", "w", encoding="ascii") as f:
                f.write("1\n")
        except OSError:
            pass


def _default_route_iface() -> Optional[str]:
    try:
        r = subprocess.run(  # nosec B603 - fixed argv, shell=False
            [_which("ip"), "-o", "-4", "route", "show", "default"],
            capture_output=True,
            timeout=5,
            text=True,
            env=_env_for_system_binaries(),
        )
        if r.returncode != 0:
            return None
        m = re.search(r"\bdev (\S+)", r.stdout or "")
        return m.group(1) if m else None
    except (subprocess.SubprocessError, OSError):
        return None


def _delete_table() -> None:
    subprocess.run(  # nosec B603 - fixed argv, shell=False
        [_which("nft"), "delete", "table", "inet", NFT_TABLE],
        capture_output=True,
        timeout=10,
        env=_env_for_system_binaries(),
    )


def _build_nft_script(unsafe_routes: list[dict], tun_dev: str, debug_log: Optional[Callable[[str], None]]) -> str:
    subnet_rules: list[str] = []
    nat_rules: list[str] = []
    seen_nat_rules: set[str] = set()
    default_iface: Optional[str] = None
    default_iface_looked_up = False

    for r in unsafe_routes:
        route = (r.get("route") or "").strip()
        if not route:
            continue
        if route in EXIT_ROUTES:
            # Both 0.0.0.0/0 and ::/0 NAT out the same (IPv4) default-route interface -
            # a host with genuinely separate v4/v6 uplinks isn't handled here.
            if not default_iface_looked_up:
                default_iface = _default_route_iface()
                default_iface_looked_up = True
            if not default_iface:
                _log(f"exit-node route {route} configured but no default route found; skipping NAT for it", debug_log)
                continue
            nat_rule = f'    iifname "{tun_dev}" oifname "{default_iface}" masquerade'
            if nat_rule not in seen_nat_rules:
                seen_nat_rules.add(nat_rule)
                nat_rules.append(nat_rule)
            continue
        try:
            net = ipaddress.ip_network(route, strict=False)
        except ValueError:
            _log(f"skipping invalid unsafe_route {route!r}", debug_log)
            continue
        family = "ip6" if net.version == 6 else "ip"
        subnet_rules.append(f'    iifname "{tun_dev}" {family} daddr {net} accept')
        subnet_rules.append(f'    {family} saddr {net} oifname "{tun_dev}" accept')

    lines = [f"table inet {NFT_TABLE} {{"]
    lines.append("    chain forward {")
    lines.append("        type filter hook forward priority filter; policy accept;")
    lines.extend(subnet_rules)
    lines.append("    }")
    if nat_rules:
        lines.append("    chain postrouting {")
        lines.append("        type nat hook postrouting priority srcnat; policy accept;")
        lines.extend(nat_rules)
        lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def apply_routes(
    unsafe_routes: list[dict],
    tun_dev: str,
    debug_log: Optional[Callable[[str], None]] = None,
) -> None:
    """
    Idempotent: given this node's full current unsafe_routes list and its tun device
    name, make them actually work on Linux - enable IP forwarding and (re)install a
    dedicated `inet ncclient_routing` nftables table for forwarding + NAT. The table is
    deleted and recreated from scratch on every call rather than diffed, which is simple
    and avoids drift; call it once per config change (see ncclient.run_poll_loop).

    Never resets ip_forward back off when routes become empty - see _set_ip_forward.
    Never raises: a routing-automation failure should be logged, not take down the poll
    loop that also needs to keep talking to the backend and running Nebula.
    """
    if not unsafe_routes:
        _delete_table()
        return

    if not shutil.which("nft"):
        _log(
            "unsafe_routes configured but 'nft' (nftables) was not found; "
            "cannot apply host forwarding/NAT rules for subnet routing / exit node",
            debug_log,
        )
        return

    _set_ip_forward(unsafe_routes)

    script = _build_nft_script(unsafe_routes, tun_dev, debug_log)
    _delete_table()
    try:
        r = subprocess.run(  # nosec B603 - fixed argv, script body is CIDR/interface-derived only, shell=False
            [_which("nft"), "-f", "-"],
            input=script,
            capture_output=True,
            timeout=10,
            text=True,
            env=_env_for_system_binaries(),
        )
        if r.returncode != 0:
            _log(f"nft apply failed: {(r.stderr or '').strip()}", debug_log)
    except (subprocess.SubprocessError, OSError) as e:
        _log(f"nft apply failed: {e}", debug_log)
