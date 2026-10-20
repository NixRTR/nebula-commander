"""
tun.dev is named after the network so a host can run one nebula per network: two
nebulas asking for the same device name fail with EBUSY on Linux. The name must
survive Linux's dev_valid_name (1-15 bytes, no '/', ':' or whitespace), and
Network.name has no character validation.
"""
import pytest
import yaml

from backend.models import Network, Node
from backend.services.config_generator import DEFAULT_TUN_DEV, build_config, tun_dev_for_network


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("home", "home"),
        ("Home Lab", "home-lab"),
        ("acme/prod:eu  west", "acme-prod-eu-we"),
        ("--edge--", "edge"),
        ("under_score", "under_score"),
        ("Café Réseau", "cafe-reseau"),
        ("a" * 40, "a" * 15),
        # Truncation must not leave a trailing separator.
        ("abcdefghijklmn opq", "abcdefghijklmn"),
        ("!!!", DEFAULT_TUN_DEV),
        ("日本語", DEFAULT_TUN_DEV),
        ("", DEFAULT_TUN_DEV),
        (None, DEFAULT_TUN_DEV),
    ],
)
def test_tun_dev_for_network(name, expected):
    assert tun_dev_for_network(name) == expected


def test_tun_dev_is_a_valid_linux_interface_name():
    for name in ("x" * 300, "a/b", "a:b", "a b\tc\n", ".", "..", "A.B"):
        dev = tun_dev_for_network(name)
        assert 1 <= len(dev.encode()) <= 15
        assert dev not in (".", "..")
        assert not any(c in dev for c in "/: \t\n")


def test_long_names_with_a_shared_prefix_collide():
    # Documented limitation: uniqueness of Network.name does not carry over past 15 bytes.
    assert tun_dev_for_network("production-east") == tun_dev_for_network("production-east-2")


def test_generated_config_uses_the_network_name():
    network = Network(id=1, name="Home Lab")
    node = Node(id=1, network_id=1, hostname="n1", ip_address="10.100.0.1", groups=[], unsafe_routes=[])

    config = yaml.safe_load(build_config(node, network, [], group_firewalls=[]))

    assert config["tun"]["dev"] == "home-lab"
