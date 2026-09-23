"""
Generate Nebula YAML config for a node from Node + Network + peer nodes.
"""
import logging
from pathlib import Path
from typing import Any, Optional

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Network, Node, NetworkDNSConfig, NetworkGroupFirewall

logger = logging.getLogger(__name__)

# Default paths in generated config (user places downloaded files here)
DEFAULT_PKI_CA = "/etc/nebula/ca.crt"
DEFAULT_PKI_CERT = "/etc/nebula/host.crt"
DEFAULT_PKI_KEY = "/etc/nebula/host.key"
DEFAULT_LISTEN_PORT = 4242


async def get_dns_client_config(
    session: AsyncSession, network_id: int
) -> Optional[tuple[str, list[str]]]:
    """
    Split-horizon DNS config for a network: (domain, dns_servers), or None if
    DNS is not enabled. dns_servers is every lighthouse's Nebula IP followed
    by the network's extra_dns_resolvers (external/fallback resolvers) - used
    both by the device-facing /dns-client-config endpoint and by mobile config
    generation, so both platforms get any configured redundancy the same way.
    """
    cfg_result = await session.execute(
        select(NetworkDNSConfig).where(NetworkDNSConfig.network_id == network_id)
    )
    cfg = cfg_result.scalar_one_or_none()
    if not cfg or not cfg.enabled:
        return None

    lighthouses_result = await session.execute(
        select(Node).where(
            Node.network_id == network_id,
            Node.is_lighthouse == True,
            Node.ip_address.isnot(None),
        )
    )
    dns_servers = [
        n.ip_address
        for n in lighthouses_result.scalars().all()
        if n.ip_address and n.ip_address.strip()
    ]
    dns_servers.extend(
        s.strip() for s in (cfg.extra_dns_resolvers or []) if s and s.strip()
    )
    return cfg.domain, dns_servers


def _default_pki() -> dict[str, str]:
    return {
        "ca": DEFAULT_PKI_CA,
        "cert": DEFAULT_PKI_CERT,
        "key": DEFAULT_PKI_KEY,
    }


def _normalize_endpoint(endpoint: str) -> str:
    """Strip http(s):// so Nebula gets host:port only (e.g. 192.168.3.125:4242)."""
    s = endpoint.strip()
    for prefix in ("https://", "http://"):
        if s.lower().startswith(prefix):
            return s[len(prefix) :].strip()
    return s


def _default_static_host_map(hosts_with_endpoint: list[tuple[str, str]]) -> dict[str, list[str]]:
    """hosts_with_endpoint: list of (nebula_ip, public_endpoint) for lighthouses and relays."""
    return {ip: [_normalize_endpoint(endpoint)] for ip, endpoint in hosts_with_endpoint}


def _relay_section(node: Node, other_relay_ips: list[str]) -> dict[str, Any]:
    """Build relay section: am_relay, use_relays, relays (empty if this node is a relay)."""
    if node.is_relay:
        return {"am_relay": True, "use_relays": True, "relays": []}
    return {"am_relay": False, "use_relays": True, "relays": other_relay_ips}


def _lighthouse_section(
    node: Node,
    other_lighthouse_ips: list[str],
) -> dict[str, Any]:
    """Build lighthouse section: am_lighthouse, hosts, optional interval. DNS is served by ncclient dnsmasq only."""
    section: dict[str, Any] = {
        "am_lighthouse": node.is_lighthouse,
        "hosts": other_lighthouse_ips,
    }
    opts = node.lighthouse_options or {}
    if node.is_lighthouse and opts.get("interval_seconds") is not None:
        section["interval"] = opts["interval_seconds"]
    return section


def _default_listen(port: int = DEFAULT_LISTEN_PORT) -> dict[str, Any]:
    return {"host": "0.0.0.0", "port": port}  # nosec B104 - Nebula node config needs all interfaces


def _collect_advertised_routes(node: Node, peer_nodes: list[Node]) -> list[dict[str, Any]]:
    """
    tun.unsafe_routes entries this node needs so it can reach subnets *other* nodes
    advertise - Nebula requires `via` (the advertising node's own Nebula IP) on every
    entry, and routes for it, without that, `nebula` refuses to even start ("via ... is
    not present"). A node never gets an entry for its own advertised routes: it already
    has direct (non-overlay) access to them, and `via` pointing at itself makes no sense.

    Each advertised route is opt-in per consumer: a route only propagates to nodes listed
    in its own "consumers" (a list of node IDs, empty by default - see nodes.py's
    update_node validation). This is deliberately NOT "every node in the network" so an
    admin can hand a route to specific nodes without exposing it network-wide.

    The advertising node also needs the CIDR baked into its own certificate's -subnets
    claim (see cert_manager._unsafe_subnets_for_cert / CertManager.resign_host_certificate)
    - Nebula silently refuses to route a subnet the via node's cert doesn't claim, so that
    half of this has to stay in sync with what's collected here.
    """
    gateways_by_route: dict[str, list[str]] = {}
    for other in peer_nodes:
        if not other.ip_address:
            continue
        for r in other.unsafe_routes or []:
            route = str(r.get("route") or "").strip()
            if not route:
                continue
            if node.id not in (r.get("consumers") or []):
                continue
            gateways_by_route.setdefault(route, []).append(other.ip_address)

    entries: list[dict[str, Any]] = []
    for route, gateways in gateways_by_route.items():
        unique_gateways = sorted(set(gateways))
        if len(unique_gateways) == 1:
            entries.append({"route": route, "via": unique_gateways[0]})
        else:
            # Multiple nodes advertising the same CIDR: Nebula's ECMP via-list form
            # (v1.10+), equally weighted.
            entries.append({"route": route, "via": [{"gateway": g} for g in unique_gateways]})
    return entries


def _default_tun(advertised_routes: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    tun: dict[str, Any] = {
        "dev": "nebula1",
        "drop_local_broadcast": False,
        "drop_multicast": False,
        "tx_queue": 500,
        "mtu": 1300,
        "routes": [],
    }
    if advertised_routes:
        tun["unsafe_routes"] = advertised_routes
    return tun


LOG_LEVELS = ("panic", "fatal", "error", "warning", "info", "debug")
LOG_FORMATS = ("json", "text")


def _logging_section(node: Node) -> dict[str, Any]:
    """Build logging section from node.logging_options with Nebula defaults."""
    opts = node.logging_options or {}
    level = (opts.get("level") or "info").lower()
    if level not in LOG_LEVELS:
        level = "info"
    fmt = (opts.get("format") or "text").lower()
    if fmt not in LOG_FORMATS:
        fmt = "text"
    section: dict[str, Any] = {"level": level, "format": fmt}
    if opts.get("disable_timestamp") is True:
        section["disable_timestamp"] = True
    ts_fmt = (opts.get("timestamp_format") or "").strip()
    if ts_fmt:
        section["timestamp_format"] = ts_fmt
    return section


def _default_firewall() -> dict[str, Any]:
    """Outbound allow all; inbound allow all (no rules)."""
    return {
        "conntrack": {
            "tcp_timeout": "120h",
            "udp_timeout": "3m",
            "default_timeout": "10m",
            "max_connections": 100000,
        },
        "outbound": [{"port": "any", "proto": "any", "host": "any"}],
        "inbound": [{"port": "any", "proto": "any", "host": "any"}],
    }


def _parse_port_range(port_range: str) -> list[int] | None:
    """
    Parse port_range string into list of ports. Returns None for 'any'.
    Format: "any" | "22" | "22,80-88,10000-10002"
    """
    s = (port_range or "").strip().lower()
    if not s or s == "any":
        return None
    ports: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                lo, hi = int(a.strip()), int(b.strip())
                if lo <= hi and 0 <= lo <= 65535 and 0 <= hi <= 65535:
                    ports.extend(range(lo, hi + 1))
            except ValueError:
                continue
        else:
            try:
                p = int(part)
                if 0 <= p <= 65535:
                    ports.append(p)
            except ValueError:
                continue
    return ports if ports else None


def _inbound_rules_from_group_firewall(inbound_rules: list[Any]) -> list[dict[str, Any]]:
    """
    Convert defined.net-style inbound rules to Nebula format.
    New shape: allowed_group, protocol, port_range, description.
    Legacy shape: group, proto, port (one port or "any") - converted for backward compat.
    Expands port_range into one Nebula rule per port; group = allowed_group, proto = protocol.
    """
    nebula_rules: list[dict[str, Any]] = []
    for r in inbound_rules or []:
        if not isinstance(r, dict):
            continue
        allowed_group = (r.get("allowed_group") or r.get("group") or "").strip()
        if not allowed_group:
            continue
        protocol = (r.get("protocol") or r.get("proto") or "any").strip().lower()
        if protocol not in ("any", "tcp", "udp", "icmp"):
            protocol = "any"
        port_range = (r.get("port_range") or str(r.get("port", "any")).strip() or "any").strip()
        ports = _parse_port_range(port_range)
        if ports is None:
            nebula_rules.append({"port": "any", "proto": protocol, "group": allowed_group})
        else:
            for port in ports:
                nebula_rules.append({"port": port, "proto": protocol, "group": allowed_group})
    return nebula_rules


def _local_cidr_rules_for_consumers(node: Node, peer_nodes: list[Node]) -> list[dict[str, Any]]:
    """
    Since Nebula 1.10, a firewall rule only matches traffic to this node's own overlay
    IP unless it sets `local_cidr` - it does NOT also cover traffic being forwarded to a
    subnet this node advertises via unsafe_routes. Without an accept rule for it, a
    gateway node would silently drop all forwarded traffic even though the
    route/cert/nftables side is otherwise correct.

    This is also the actual enforcement point for a route's "consumers" (the "Used by"
    picker) - the only other reference to consumers is _collect_advertised_routes,
    which merely decides whose *own* config gets a `via` entry, and has no effect on
    what the gateway itself will forward. One rule per (route, consumer), scoped with
    `cidr` to that consumer's certificate-verified Nebula overlay IP (Nebula ties `cidr`
    to the peer's cert, so this isn't a spoofable source-IP check) - a route with no
    consumers yet gets no accept rule at all, so "a route reaches nobody until an admin
    explicitly says who it's for" (docs/unsafe-routes.md) is now true at the firewall
    level, not just for config distribution.
    """
    ip_by_id = {n.id: n.ip_address for n in peer_nodes if n.ip_address}
    rules: list[dict[str, Any]] = []
    for r in node.unsafe_routes or []:
        route = str(r.get("route") or "").strip()
        if not route:
            continue
        for consumer_id in r.get("consumers") or []:
            consumer_ip = ip_by_id.get(consumer_id)
            if consumer_ip:
                rules.append({"port": "any", "proto": "any", "cidr": f"{consumer_ip}/32", "local_cidr": route})
    return rules


def _firewall_section(
    network: Network,
    node: Node,
    group_firewalls: list[Any],
    peer_nodes: list[Node],
) -> dict[str, Any]:
    """
    Defined.net style: no network firewall. Outbound allow all.
    Inbound deny by default; allow only rules from the node's single group.
    Node has one group (node.groups[0]); that group's inbound_rules define who can reach this node.
    """
    section: dict[str, Any] = {
        "conntrack": {
            "tcp_timeout": "120h",
            "udp_timeout": "3m",
            "default_timeout": "10m",
            "max_connections": 100000,
        },
        "outbound": [{"port": "any", "proto": "any", "host": "any"}],
    }
    node_group = (node.groups or [None])[0] if (node.groups and len(node.groups) > 0) else None
    group_by_name = {gf.group_name: gf for gf in group_firewalls if getattr(gf, "group_name", None)}
    gf = group_by_name.get(node_group) if node_group else None
    inbound_rules_raw = getattr(gf, "inbound_rules", None) or [] if gf else []

    if not inbound_rules_raw:
        section["inbound"] = [{"port": "any", "proto": "any", "host": "any"}]
    else:
        section["inbound_action"] = "drop"
        section["inbound"] = _inbound_rules_from_group_firewall(inbound_rules_raw)
        if not section["inbound"]:
            section["inbound"] = [{"port": "any", "proto": "any", "host": "any"}]

    section["inbound"] = section["inbound"] + _local_cidr_rules_for_consumers(node, peer_nodes)
    return section


def _punchy_section(node: Node) -> dict[str, Any]:
    """Build punchy section. Nested format: punch, respond, optional delay/respond_delay."""
    opts = node.punchy_options or {}
    section: dict[str, Any] = {
        "punch": True,
        "respond": opts.get("respond", True),
    }
    if opts.get("delay"):
        section["delay"] = opts["delay"]
    if opts.get("respond_delay"):
        section["respond_delay"] = opts["respond_delay"]
    return section


def build_config(
    node: Node,
    network: Network,
    peer_nodes: list[Node],
    group_firewalls: list[Any],
    inline_pki: Optional[tuple[str, str, str]] = None,
    mobile_dns: Optional[dict[str, list[str]]] = None,
) -> str:
    """
    Build Nebula YAML config for the given node.
    peer_nodes: all other nodes in the same network (for lighthouses list and static_host_map).
    inline_pki: optional (ca_pem, cert_pem, key_pem) to embed certs in config (OS-independent; no file paths).
    mobile_dns: optional {"dns_resolvers": [...], "match_domains": [...]} - adds the Mobile Nebula
    app's split-horizon DNS extension block (mobile_nebula:) for iOS/Android nodes.
    """
    # Lighthouses and relays with public_endpoint (for static_host_map)
    hosts_with_endpoint = [
        (n.ip_address, n.public_endpoint)
        for n in peer_nodes
        if (n.is_lighthouse or n.is_relay) and n.public_endpoint and n.ip_address
    ]
    lighthouses_with_endpoint = [
        (n.ip_address, n.public_endpoint)
        for n in peer_nodes
        if n.is_lighthouse and n.public_endpoint and n.ip_address
    ]
    other_lighthouse_ips = [ip for ip, _ in lighthouses_with_endpoint if ip != node.ip_address]
    other_relay_ips = [
        n.ip_address for n in peer_nodes
        if n.is_relay and n.ip_address and n.ip_address != node.ip_address
    ]

    if inline_pki is not None:
        ca_pem, cert_pem, key_pem = inline_pki
        pki_section: dict[str, Any] = {
            "ca": ca_pem.rstrip() + "\n",
            "cert": cert_pem.rstrip() + "\n",
            "key": key_pem.rstrip() + "\n",
        }
    else:
        pki_section = _default_pki()

    config: dict[str, Any] = {
        "pki": pki_section,
        "static_host_map": _default_static_host_map(hosts_with_endpoint) if hosts_with_endpoint else {},
        "lighthouse": _lighthouse_section(node, other_lighthouse_ips),
        "relay": _relay_section(node, other_relay_ips),
        "listen": _default_listen(),
        "punchy": _punchy_section(node),
        "tun": _default_tun(_collect_advertised_routes(node, peer_nodes)),
        "logging": _logging_section(node),
        "firewall": _firewall_section(network, node, group_firewalls, peer_nodes),
    }

    # Remove empty static_host_map so Nebula doesn't complain
    if not config["static_host_map"]:
        del config["static_host_map"]

    if mobile_dns and mobile_dns.get("dns_resolvers"):
        config["mobile_nebula"] = {
            "dns_resolvers": mobile_dns["dns_resolvers"],
            "match_domains": mobile_dns.get("match_domains") or [],
        }

    return yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)


async def generate_config_for_node(
    session: AsyncSession,
    node_id: int,
    inline_pki: Optional[tuple[str, str, str]] = None,
    mobile_dns: Optional[dict[str, list[str]]] = None,
) -> Optional[str]:
    """
    Load node + network + peers and return generated YAML config, or None if node not found.
    inline_pki: optional (ca_pem, cert_pem, key_pem) to embed in config (no file paths).
    mobile_dns: optional {"dns_resolvers": [...], "match_domains": [...]} for mobile nodes;
    see build_config().
    """
    result = await session.execute(
        select(Node).where(Node.id == node_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        return None

    result = await session.execute(
        select(Network).where(Network.id == node.network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        return None

    result = await session.execute(
        select(Node).where(Node.network_id == node.network_id)
    )
    all_nodes = list(result.scalars().all())
    peer_nodes = [n for n in all_nodes if n.id != node.id]

    result = await session.execute(
        select(NetworkGroupFirewall).where(NetworkGroupFirewall.network_id == network.id)
    )
    group_firewalls = list(result.scalars().all())

    return build_config(
        node, network, peer_nodes, group_firewalls, inline_pki=inline_pki, mobile_dns=mobile_dns
    )
