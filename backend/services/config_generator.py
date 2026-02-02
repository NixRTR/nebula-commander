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
from ..models import Network, Node

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


def _default_static_host_map(lighthouses: list[tuple[str, str]]) -> dict[str, list[str]]:
    """lighthouses: list of (nebula_ip, public_endpoint)."""
    return {ip: [endpoint] for ip, endpoint in lighthouses}


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
                "host": opts.get("dns_host") or "0.0.0.0",
                "port": opts.get("dns_port") or 53,
            }
        if opts.get("interval_seconds") is not None:
            section["interval"] = opts["interval_seconds"]
    return section


def _default_listen(port: int = DEFAULT_LISTEN_PORT) -> dict[str, Any]:
    return {"host": "0.0.0.0", "port": port}


def _default_tun() -> dict[str, Any]:
    return {
        "dev": "nebula1",
        "drop_local_broadcast": False,
        "drop_multicast": False,
        "tx_queue": 500,
        "mtu": 1300,
        "routes": [],
    }


def _default_logging() -> dict[str, str]:
    return {"level": "info", "format": "text"}


def _default_firewall() -> dict[str, Any]:
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


def build_config(
    node: Node,
    network: Network,
    peer_nodes: list[Node],
) -> str:
    """
    Build Nebula YAML config for the given node.
    peer_nodes: all other nodes in the same network (for lighthouses list and static_host_map).
    """
    # Lighthouses with public_endpoint (for static_host_map and hosts list)
    lighthouses_with_endpoint = [
        (n.ip_address, n.public_endpoint)
        for n in peer_nodes
        if n.is_lighthouse and n.public_endpoint and n.ip_address
    ]
    other_lighthouse_ips = [
        ip for ip, _ in lighthouses_with_endpoint
        if ip != node.ip_address
    ]

    config: dict[str, Any] = {
        "pki": _default_pki(),
        "static_host_map": _default_static_host_map(lighthouses_with_endpoint) if lighthouses_with_endpoint else {},
        "lighthouse": _lighthouse_section(node, other_lighthouse_ips),
        "listen": _default_listen(),
        "punchy": True,
        "punch_back": True,
        "tun": _default_tun(),
        "logging": _default_logging(),
        "firewall": _default_firewall(),
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

    return build_config(node, network, peer_nodes)
