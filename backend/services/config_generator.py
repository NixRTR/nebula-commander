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
from ..models import Network, Node, NetworkGroupFirewall

logger = logging.getLogger(__name__)

# Default paths in generated config (user places downloaded files here)
DEFAULT_PKI_CA = "/etc/nebula/ca.crt"
DEFAULT_PKI_CERT = "/etc/nebula/host.crt"
DEFAULT_PKI_KEY = "/etc/nebula/host.key"
DEFAULT_LISTEN_PORT = 4242


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
    """Build lighthouse section: am_lighthouse, hosts, optional serve_dns/dns/interval."""
    section: dict[str, Any] = {
        "am_lighthouse": node.is_lighthouse,
        "hosts": other_lighthouse_ips,
    }
    opts = node.lighthouse_options or {}
    if node.is_lighthouse and opts:
        if opts.get("serve_dns") is True:
            section["serve_dns"] = True
            section["dns"] = {
                "host": opts.get("dns_host") or "0.0.0.0",  # nosec B104 - Nebula node config needs all interfaces
                "port": opts.get("dns_port") or 53,
            }
        if opts.get("interval_seconds") is not None:
            section["interval"] = opts["interval_seconds"]
    return section


def _default_listen(port: int = DEFAULT_LISTEN_PORT) -> dict[str, Any]:
    return {"host": "0.0.0.0", "port": port}  # nosec B104 - Nebula node config needs all interfaces


def _default_tun() -> dict[str, Any]:
    return {
        "dev": "nebula1",
        "drop_local_broadcast": False,
        "drop_multicast": False,
        "tx_queue": 500,
        "mtu": 1300,
        "routes": [],
    }


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


def _firewall_section(
    network: Network,
    node: Node,
    group_firewalls: list[Any],
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
        return section

    section["inbound_action"] = "drop"
    section["inbound"] = _inbound_rules_from_group_firewall(inbound_rules_raw)
    if not section["inbound"]:
        section["inbound"] = [{"port": "any", "proto": "any", "host": "any"}]
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
) -> str:
    """
    Build Nebula YAML config for the given node.
    peer_nodes: all other nodes in the same network (for lighthouses list and static_host_map).
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

    config: dict[str, Any] = {
        "pki": _default_pki(),
        "static_host_map": _default_static_host_map(hosts_with_endpoint) if hosts_with_endpoint else {},
        "lighthouse": _lighthouse_section(node, other_lighthouse_ips),
        "relay": _relay_section(node, other_relay_ips),
        "listen": _default_listen(),
        "punchy": _punchy_section(node),
        "tun": _default_tun(),
        "logging": _logging_section(node),
        "firewall": _firewall_section(network, node, group_firewalls),
    }

    # Remove empty static_host_map so Nebula doesn't complain
    if not config["static_host_map"]:
        del config["static_host_map"]

    return yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)


async def generate_config_for_node(
    session: AsyncSession,
    node_id: int,
) -> Optional[str]:
    """
    Load node + network + peers and return generated YAML config, or None if node not found.
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

    return build_config(node, network, peer_nodes, group_firewalls)
