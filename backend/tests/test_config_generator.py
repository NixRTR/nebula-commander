"""
Tests for the subnet-router/exit-node "consumers" access control fix: a
gateway's config must only grant local_cidr-forwarded access to nodes
actually listed as consumers of that route, and none at all for a route with
no consumers yet. See docs/unsafe-routes.md and
backend/services/config_generator.py::_local_cidr_rules_for_consumers.

build_config()/_firewall_section() are plain functions over already-loaded
Node/Network objects, so these run against directly-constructed model
instances - no DB session or fixtures needed.
"""
import yaml

from backend.models import Network, Node, NetworkGroupFirewall
from backend.services.config_generator import build_config


def _local_cidr_rules(config: dict) -> list[dict]:
    return [r for r in config["firewall"]["inbound"] if r.get("local_cidr")]


def test_only_listed_consumer_gets_a_local_cidr_rule():
    network = Network(id=1, name="test-net")
    gateway = Node(
        id=1,
        network_id=1,
        hostname="gateway",
        ip_address="10.100.0.1",
        groups=[],
        unsafe_routes=[{"route": "192.168.1.0/24", "source": "manual", "consumers": [2]}],
    )
    consumer = Node(id=2, network_id=1, hostname="consumer", ip_address="10.100.0.2", groups=[], unsafe_routes=[])
    not_a_consumer = Node(id=3, network_id=1, hostname="bystander", ip_address="10.100.0.3", groups=[], unsafe_routes=[])

    config = yaml.safe_load(build_config(gateway, network, [consumer, not_a_consumer], group_firewalls=[]))

    rules = _local_cidr_rules(config)
    assert rules == [{"port": "any", "proto": "any", "cidr": "10.100.0.2/32", "local_cidr": "192.168.1.0/24"}]
    assert not any(r.get("cidr") == "10.100.0.3/32" for r in config["firewall"]["inbound"])


def test_route_with_no_consumers_gets_no_accept_rule():
    network = Network(id=1, name="test-net")
    gateway = Node(
        id=1,
        network_id=1,
        hostname="gateway",
        ip_address="10.100.0.1",
        groups=["servers"],
        unsafe_routes=[{"route": "192.168.1.0/24", "source": "manual", "consumers": []}],
    )
    peer = Node(id=2, network_id=1, hostname="peer", ip_address="10.100.0.2", groups=["servers"], unsafe_routes=[])

    config = yaml.safe_load(build_config(gateway, network, [peer], group_firewalls=[]))

    assert _local_cidr_rules(config) == []


def test_consumer_rule_survives_a_restrictive_group_firewall():
    """A gateway whose group has its own locked-down inbound ACL (inbound_action:
    drop, only port 22 from its own group) must still forward to a listed
    consumer for the advertised subnet - the consumer rule is independent of
    whatever general ACL governs direct traffic to the gateway's own IP."""
    network = Network(id=1, name="test-net")
    group_fw = NetworkGroupFirewall(
        network_id=1,
        group_name="servers",
        inbound_rules=[{"allowed_group": "servers", "protocol": "tcp", "port_range": "22"}],
    )
    gateway = Node(
        id=1,
        network_id=1,
        hostname="gateway",
        ip_address="10.100.0.1",
        groups=["servers"],
        unsafe_routes=[{"route": "192.168.1.0/24", "source": "manual", "consumers": [2]}],
    )
    consumer = Node(id=2, network_id=1, hostname="consumer", ip_address="10.100.0.2", groups=["servers"], unsafe_routes=[])

    config = yaml.safe_load(build_config(gateway, network, [consumer], group_firewalls=[group_fw]))

    assert config["firewall"]["inbound_action"] == "drop"
    assert _local_cidr_rules(config) == [
        {"port": "any", "proto": "any", "cidr": "10.100.0.2/32", "local_cidr": "192.168.1.0/24"}
    ]


def test_consumer_missing_ip_address_is_skipped():
    """A consumer that hasn't been assigned a Nebula IP yet (not yet enrolled)
    can't be matched by `cidr`, so it's silently skipped rather than emitting
    a malformed rule - it'll get access once its IP is assigned and the
    gateway's config is regenerated."""
    network = Network(id=1, name="test-net")
    gateway = Node(
        id=1,
        network_id=1,
        hostname="gateway",
        ip_address="10.100.0.1",
        groups=[],
        unsafe_routes=[{"route": "192.168.1.0/24", "source": "manual", "consumers": [2]}],
    )
    unenrolled_consumer = Node(id=2, network_id=1, hostname="pending", ip_address=None, groups=[], unsafe_routes=[])

    config = yaml.safe_load(build_config(gateway, network, [unenrolled_consumer], group_firewalls=[]))

    assert _local_cidr_rules(config) == []
