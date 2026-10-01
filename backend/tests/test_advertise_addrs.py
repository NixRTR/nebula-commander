"""
lighthouse.advertise_addrs: extra underlay addresses a node reports to lighthouses (port
forwards, multiple uplinks). IP literals only - nebula resolves hostnames once at startup
and won't start if the lookup fails. Lighthouses never send host updates, so they never
get the key.
"""
import pytest
import yaml

from backend.models import Network, Node
from backend.services.config_generator import build_config, normalize_advertise_addrs


@pytest.mark.parametrize(
    "raw, expected",
    [
        (["203.0.113.7:4242"], ["203.0.113.7:4242"]),
        ([" 192.168.1.10:4242 "], ["192.168.1.10:4242"]),
        (["[2001:db8::1]:4242"], ["[2001:db8::1]:4242"]),
        (["203.0.113.7:0"], ["203.0.113.7:0"]),
        (["203.0.113.7:04242", "203.0.113.7:4242"], ["203.0.113.7:4242"]),
        ([], []),
    ],
)
def test_valid_addrs_are_normalized(raw, expected):
    assert normalize_advertise_addrs(raw, "10.100.0.0/24") == expected


@pytest.mark.parametrize(
    "raw",
    [
        "node.example.com:4242",  # hostname
        "203.0.113.7",  # no port
        "2001:db8::1:4242",  # IPv6 without brackets
        "203.0.113.7:65536",
        "203.0.113.7:http",
        "0.0.0.0:4242",
        "127.0.0.1:4242",
        "169.254.1.1:4242",
        "224.0.0.1:4242",
        "10.100.0.5:4242",  # inside the Nebula network
        "255.255.255.255:4242",  # broadcast
        "240.0.0.1:4242",  # reserved 240.0.0.0/4
        "[::ffff:203.0.113.7]:4242",  # IPv4-mapped IPv6
        "203.0.113.7:4242,198.51.100.2:4242",  # comma-joined in one entry
    ],
)
def test_invalid_addrs_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_advertise_addrs([raw], "10.100.0.0/24")


@pytest.mark.parametrize("raw", ["203.0.113.7:4242,198.51.100.2:4242", "203.0.113.7:4242 198.51.100.2:4242"])
def test_comma_joined_entry_gets_a_clear_message(raw):
    with pytest.raises(ValueError, match="one address per entry"):
        normalize_advertise_addrs([raw], "10.100.0.0/24")


def test_too_many_addrs_are_rejected():
    with pytest.raises(ValueError):
        normalize_advertise_addrs([f"203.0.113.{i}:4242" for i in range(1, 10)])


def _node(id: int, ip: str, addrs=None, lighthouse=False) -> Node:
    return Node(
        id=id, network_id=1, hostname=f"n{id}", ip_address=ip, groups=[], unsafe_routes=[],
        is_lighthouse=lighthouse, is_relay=False, advertise_addrs=addrs or [],
    )


def test_node_gets_its_own_advertise_addrs():
    network = Network(id=1, name="net", subnet_cidr="10.100.0.0/24")
    me = _node(1, "10.100.0.1", ["203.0.113.7:4242"])
    lighthouse = _node(2, "10.100.0.2", lighthouse=True)

    config = yaml.safe_load(build_config(me, network, [lighthouse], group_firewalls=[]))

    assert config["lighthouse"]["advertise_addrs"] == ["203.0.113.7:4242"]


def test_lighthouse_never_gets_advertise_addrs():
    network = Network(id=1, name="net", subnet_cidr="10.100.0.0/24")
    me = _node(1, "10.100.0.1", ["203.0.113.7:4242"], lighthouse=True)

    config = yaml.safe_load(build_config(me, network, [], group_firewalls=[]))

    assert "advertise_addrs" not in config["lighthouse"]


def test_no_addrs_leaves_config_unchanged():
    network = Network(id=1, name="net", subnet_cidr="10.100.0.0/24")
    lighthouse = _node(2, "10.100.0.2", lighthouse=True)
    without = _node(1, "10.100.0.1")
    legacy = _node(1, "10.100.0.1")
    legacy.advertise_addrs = None  # rows that predate the column

    assert build_config(without, network, [lighthouse], group_firewalls=[]) == build_config(
        legacy, network, [lighthouse], group_firewalls=[]
    )
    assert "advertise_addrs" not in yaml.safe_load(build_config(without, network, [lighthouse], group_firewalls=[]))["lighthouse"]
