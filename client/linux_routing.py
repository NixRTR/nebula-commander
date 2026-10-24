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
drop policy or an explicit drop, this module's accept rules in its nft_table() do not override
it. The two would need to be reconciled manually in that scenario; nothing here attempts
to detect or fix that.
"""
import ipaddress
import os
import re
import shlex
import shutil
import subprocess  # nosec B404 - used with shell=False and validated/fixed args
import sys
from typing import Callable, Optional

_SYSTEM_LIBRARY_ENV_STRIP = ("LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT", "LIBPATH")

# One table per tun device (nft_table), so ncclient instances for different networks on
# one host don't delete each other's rules. ncclient before 0.8.0 used this name alone; the
# instance on LEGACY_TUN_DEV removes that table.
NFT_TABLE = "ncclient_routing"
LEGACY_TUN_DEV = "nebula1"
EXIT_ROUTES = ("0.0.0.0/0", "::/0")
# `ip rule pref 32739 iif <dev> lookup main` while <dev> forwards routes: traffic this
# host forwards for a network it's a gateway for leaves by the normal uplink, not by this
# host's own exit node (client/exit_routing.py, prefs 32740-32742). Without it a gateway
# that also uses an exit node in another network sends the forwarded traffic into that
# tunnel un-NATed and the far end drops it.
GATEWAY_RULE_PREF = 32739

_DOCKER_PREFIXES = ("docker", "br-", "veth", "virbr")
_ETHERNET_PREFIXES = ("en", "eth")
_WIFI_PREFIXES = ("wl",)
# "nebula1" is the legacy shared device; "nc-" is the prefix the server generates.
_NEBULA_PREFIXES = ("nebula", "nc-")


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

def is_foreign_interface(ifname: str) -> bool:
    """True if ifname exists on this host and isn't a tun device - e.g. a node config whose
    tun.dev says "eth0". Nebula itself fails to start then (the kernel won't turn an
    existing non-tun device into a tun), but ncclient must not point routing, DNS or
    NetworkManager handling at that interface either."""
    return os.path.isdir(f"/sys/class/net/{ifname}") and not os.path.exists(f"/sys/class/net/{ifname}/tun_flags")


def nft_table(tun_dev: str) -> str:
    """This device's nftables table, e.g. "ncclient_routing_nc_home". Server-issued names
    are "nebula1" or "nc-" plus [a-z0-9-], so mapping "-" to "_" can't make two equal."""
    return f"{NFT_TABLE}_{re.sub(r'[^A-Za-z0-9_]', '_', tun_dev)}"


def docker_user_comment(tun_dev: str) -> str:
    """Comment on this device's DOCKER-USER rules, e.g. "ncclient:nc-home"."""
    return f"{DOCKER_USER_COMMENT}:{tun_dev}"


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
    # Another ncclient's nebula on this host: its device is named after its network, so
    # match on tun type as well as the legacy nebula* name. Other tun-based VPNs
    # (e.g. OpenVPN's tun0) land here too.
    if ifname.startswith(_NEBULA_PREFIXES) or os.path.exists(f"/sys/class/net/{ifname}/tun_flags"):
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
    excluded so a node never offers to advertise its own overlay interface. Other tun
    interfaces (a different ncclient/network on the same host) are still included as
    kind="nebula".
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

def _set_ip_forward(routes: list[dict], debug_log: Optional[Callable[[str], None]] = None) -> None:
    """One-way enable only - never written back to 0. This runs on router-flavored
    hosts where forwarding may be wanted for other reasons; ncclient only ever adds
    host config it doesn't already own, it doesn't revert state on the way out.

    In a container (the Docker image runs with host networking) /proc/sys is mounted
    read-only unless the container is privileged, so the write fails: say so, since the
    gateway silently forwards nothing until the host enables it."""
    paths = ["/proc/sys/net/ipv4/ip_forward"]
    if any(":" in (r.get("route") or "") for r in routes):
        paths.append("/proc/sys/net/ipv6/conf/all/forwarding")
    for path in paths:
        try:
            with open(path, "w", encoding="ascii") as f:
                f.write("1\n")
        except OSError:
            pass
        try:
            with open(path, "r", encoding="ascii") as f:
                enabled = f.read().strip() == "1"
        except OSError:
            enabled = False
        if not enabled:
            key = path.removeprefix("/proc/sys/").replace("/", ".")
            _log(
                f"IP forwarding is off and ncclient couldn't turn it on ({key}): this gateway forwards "
                f"nothing until it's enabled. In Docker, set `sysctl -w {key}=1` on the host (persist it in "
                "/etc/sysctl.d/) or run the container privileged.",
                debug_log,
            )


# --- Docker's FORWARD policy ------------------------------------------------------
# Docker sets the iptables FORWARD policy to DROP. ncclient's own nftables table can
# accept, but a drop in another table at the same hook still drops the packet, so on a
# host running Docker the gateway forwarded nothing. Docker's documented place for
# user rules is the DOCKER-USER chain; ncclient's rules there carry a per-device comment
# (docker_user_comment) so each instance finds and replaces only its own. ncclient before
# 0.8.0 used this comment alone; the instance on LEGACY_TUN_DEV removes those rules.
DOCKER_USER_COMMENT = "ncclient"


def _docker_user_iptables() -> Optional[str]:
    """The iptables binary that sees Docker's DOCKER-USER chain, or None (no Docker, or
    Docker not managing iptables). The host may use the legacy backend while this
    image's iptables defaults to nft, hence trying both."""
    for name in ("iptables", "iptables-legacy"):
        binary = shutil.which(name)
        if not binary:
            continue
        try:
            r = subprocess.run(  # nosec B603 - fixed argv, shell=False
                [binary, "-w", "-n", "-L", "DOCKER-USER"],
                capture_output=True, timeout=10, text=True, env=_env_for_system_binaries(),
            )
        except (subprocess.SubprocessError, OSError):
            continue
        if r.returncode == 0:
            return binary
    return None


def docker_user_rules(unsafe_routes: list[dict], tun_dev: str, uplink: Optional[str]) -> list[list[str]]:
    """iptables -I DOCKER-USER rule specs (without the binary) mirroring the nftables
    forward rules _build_nft_script installs (pure, for tests)."""
    tag = ["-m", "comment", "--comment", docker_user_comment(tun_dev), "-j", "ACCEPT"]
    rules: list[list[str]] = []
    exit_done = False
    for r in unsafe_routes:
        route = (r.get("route") or "").strip()
        if not route:
            continue
        if route in EXIT_ROUTES:
            if exit_done or not uplink:
                continue
            exit_done = True
            rules.append(["-i", tun_dev, "-o", uplink, *tag])
            rules.append(["-i", uplink, "-o", tun_dev, "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", *tag])
            continue
        try:
            net = ipaddress.ip_network(route, strict=False)
        except ValueError:
            continue
        if net.version != 4:
            continue  # ip6tables' DOCKER-USER only exists with Docker's ipv6 enabled; not handled
        rules.append(["-i", tun_dev, "-d", str(net), *tag])
        rules.append(["-s", str(net), "-o", tun_dev, *tag])
    return rules


def _remove_docker_user_rules(binary: str, tun_dev: str) -> None:
    comments = {docker_user_comment(tun_dev)}
    if tun_dev == LEGACY_TUN_DEV:
        comments.add(DOCKER_USER_COMMENT)
    try:
        r = subprocess.run(  # nosec B603 - fixed argv, shell=False
            [binary, "-w", "-S", "DOCKER-USER"],
            capture_output=True, timeout=10, text=True, env=_env_for_system_binaries(),
        )
    except (subprocess.SubprocessError, OSError):
        return
    for line in (r.stdout or "").splitlines():
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if parts[:2] != ["-A", "DOCKER-USER"] or not any(
            parts[i] == "--comment" and parts[i + 1] in comments for i in range(len(parts) - 1)
        ):
            continue
        spec = parts[2:]
        subprocess.run(  # nosec B603 - argv from iptables' own -S output of our own rules, shell=False
            [binary, "-w", "-D", "DOCKER-USER", *spec],
            capture_output=True, timeout=10, env=_env_for_system_binaries(),
        )


def _docker_forward_rules(
    unsafe_routes: list[dict], tun_dev: str, debug_log: Optional[Callable[[str], None]]
) -> None:
    """Replace ncclient's DOCKER-USER rules with ones for unsafe_routes (none = remove).
    A no-op on hosts without Docker's chain. Never raises."""
    try:
        _apply_docker_user_rules(unsafe_routes, tun_dev, debug_log)
    except (subprocess.SubprocessError, OSError) as e:
        _log(f"Docker FORWARD rules not updated: {e}", debug_log)


def _apply_docker_user_rules(
    unsafe_routes: list[dict], tun_dev: str, debug_log: Optional[Callable[[str], None]]
) -> None:
    binary = _docker_user_iptables()
    if not binary:
        return
    _remove_docker_user_rules(binary, tun_dev)
    if not unsafe_routes:
        return
    uplink = _default_route_iface() if any((r.get("route") or "") in EXIT_ROUTES for r in unsafe_routes) else None
    for spec in docker_user_rules(unsafe_routes, tun_dev, uplink):
        r = subprocess.run(  # nosec B603 - fixed argv; CIDRs validated, tun_dev/uplink from config/ip(8)
            [binary, "-w", "-I", "DOCKER-USER", *spec],
            capture_output=True, timeout=10, text=True, env=_env_for_system_binaries(),
        )
        if r.returncode != 0:
            _log(f"Docker FORWARD rule failed ({' '.join(spec)}): {(r.stderr or '').strip()}", debug_log)


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


def _set_gateway_rule(tun_dev: str, on: bool) -> None:
    """Add (on) or remove this device's GATEWAY_RULE_PREF rule, IPv4 and IPv6."""
    for fam in ("-4", "-6"):
        for _ in range(8):  # remove every copy, e.g. after a crash mid-update
            r = subprocess.run(  # nosec B603 - fixed argv, tun_dev from config, shell=False
                [_which("ip"), fam, "rule", "del", "pref", str(GATEWAY_RULE_PREF), "iif", tun_dev],
                capture_output=True, timeout=5, env=_env_for_system_binaries(),
            )
            if r.returncode != 0:
                break
        if on:
            subprocess.run(  # nosec B603 - fixed argv, shell=False
                [_which("ip"), fam, "rule", "add", "pref", str(GATEWAY_RULE_PREF), "iif", tun_dev, "lookup", "main"],
                capture_output=True, timeout=5, env=_env_for_system_binaries(),
            )


def _delete_table(tun_dev: str) -> None:
    """Delete this device's table (and, on LEGACY_TUN_DEV, the pre-0.8.0 shared one)."""
    tables = [nft_table(tun_dev)] + ([NFT_TABLE] if tun_dev == LEGACY_TUN_DEV else [])
    for table in tables:
        subprocess.run(  # nosec B603 - fixed argv, table name sanitised by nft_table, shell=False
            [_which("nft"), "delete", "table", "inet", table],
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

    lines = [f"table inet {nft_table(tun_dev)} {{"]
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
    name, make them actually work on Linux - enable IP forwarding and (re)install the
    device's own `inet ncclient_routing_<dev>` nftables table for forwarding + NAT. The table is
    deleted and recreated from scratch on every call rather than diffed, which is simple
    and avoids drift; call it once per config change (see ncclient.run_poll_loop).

    Never resets ip_forward back off when routes become empty - see _set_ip_forward.
    Never raises: a routing-automation failure should be logged, not take down the poll
    loop that also needs to keep talking to the backend and running Nebula.
    """
    if not unsafe_routes:
        _delete_table(tun_dev)
        _docker_forward_rules([], tun_dev, debug_log)
        _set_gateway_rule(tun_dev, False)
        return

    if is_foreign_interface(tun_dev):
        _log(f"Not applying subnet routing: tun device {tun_dev!r} is an existing non-tun interface", debug_log)
        _delete_table(tun_dev)
        _docker_forward_rules([], tun_dev, debug_log)
        _set_gateway_rule(tun_dev, False)
        return

    if not shutil.which("nft"):
        _log(
            "unsafe_routes configured but 'nft' (nftables) was not found; "
            "cannot apply host forwarding/NAT rules for subnet routing / exit node",
            debug_log,
        )
        return

    _set_ip_forward(unsafe_routes, debug_log)
    _docker_forward_rules(unsafe_routes, tun_dev, debug_log)
    _set_gateway_rule(tun_dev, True)

    script = _build_nft_script(unsafe_routes, tun_dev, debug_log)
    _delete_table(tun_dev)
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
