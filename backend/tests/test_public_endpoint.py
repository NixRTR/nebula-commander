"""
Every node can have a public endpoint, and every peer's static_host_map lists them all
(not just lighthouses/relays) so nodes can reach each other without asking a lighthouse.

Because each endpoint lands in every peer's config, a malformed one would stop nebula
on the whole network ("missing port in address") - so they're validated on save and
invalid stored values are skipped when building configs.
"""
import pytest
import yaml

from backend.models import Network, Node
from backend.services.config_generator import build_config, normalize_public_endpoint


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("node.example.com:4242", "node.example.com:4242"),
        ("  203.0.113.7:4242  ", "203.0.113.7:4242"),
        ("[2001:db8::1]:4242", "[2001:db8::1]:4242"),
        ("https://node.example.com:4242/", "node.example.com:4242"),
        ("node.example.com:04242", "node.example.com:4242"),
    ],
)
def test_valid_endpoints_are_normalized(raw, expected):
    assert normalize_public_endpoint(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "node.example.com",  # no port - nebula: "missing port in address"
        "203.0.113.7",
        "2001:db8::1:4242",  # IPv6 without brackets
        "[2001:db8::1]",
        "node.example.com:0",
        "node.example.com:65536",
        "node.example.com:http",
        "not a host:4242",
        ":4242",
    ],
)
def test_invalid_endpoints_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_public_endpoint(raw)


def _node(id: int, ip: str, endpoint=None, lighthouse=False) -> Node:
    return Node(
        id=id, network_id=1, hostname=f"n{id}", ip_address=ip, groups=[], unsafe_routes=[],
        is_lighthouse=lighthouse, is_relay=False, public_endpoint=endpoint,
    )


def test_static_host_map_includes_every_peer_with_an_endpoint():
    network = Network(id=1, name="net")
    me = _node(1, "10.100.0.1")
    lighthouse = _node(2, "10.100.0.2", "lh.example.com:4242", lighthouse=True)
    plain_peer = _node(3, "10.100.0.3", "203.0.113.7:4242")
    no_endpoint = _node(4, "10.100.0.4")

    config = yaml.safe_load(build_config(me, network, [lighthouse, plain_peer, no_endpoint], group_firewalls=[]))

    assert config["static_host_map"] == {
        "10.100.0.2": ["lh.example.com:4242"],
        "10.100.0.3": ["203.0.113.7:4242"],
    }
    # Only real lighthouses are used as lighthouses
    assert config["lighthouse"]["hosts"] == ["10.100.0.2"]


def test_invalid_stored_endpoint_is_left_out_instead_of_breaking_the_config():
    network = Network(id=1, name="net")
    me = _node(1, "10.100.0.1")
    lighthouse = _node(2, "10.100.0.2", "lh.example.com:4242", lighthouse=True)
    stale = _node(3, "10.100.0.3", "old-lighthouse.example.com")  # saved before validation, no port

    config = yaml.safe_load(build_config(me, network, [lighthouse, stale], group_firewalls=[]))

    assert config["static_host_map"] == {"10.100.0.2": ["lh.example.com:4242"]}
