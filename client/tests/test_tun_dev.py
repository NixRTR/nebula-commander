"""
The server names tun.dev after the network, so the Linux client must find its
interface by that name rather than by a "nebula" substring - and must not pick up
another ncclient's interface when a host is in more than one network.
"""
import pytest

from client import dns_apply, linux_routing, ncclient


def test_tun_dev_from_config():
    assert ncclient._tun_dev_from_config(b"tun:\n  dev: home-lab\n") == "home-lab"
    assert ncclient._tun_dev_from_config(b"tun: {}\n") is None
    assert ncclient._tun_dev_from_config(b"- not\n- a mapping\n") is None
    assert ncclient._tun_dev_from_config(b"tun: [\n") is None


@pytest.mark.parametrize("dev", ["home-lab", "nebula1", "a_b.c"])
def test_safe_tun_dev_accepts_interface_names(dev):
    assert dns_apply._safe_tun_dev(dev) == dev


@pytest.mark.parametrize("dev", [None, "", ".", "..", "a" * 16, "a b", "a/b", "a\n[main]"])
def test_safe_tun_dev_rejects_anything_else(dev):
    assert dns_apply._safe_tun_dev(dev) is None


def test_interface_lookup_uses_tun_dev_not_the_nebula_substring(monkeypatch):
    present = {"/sys/class/net/home-lab"}
    monkeypatch.setattr(dns_apply.os.path, "isdir", lambda p: p in present)

    def no_ip_link(*a, **k):
        raise AssertionError("must not fall back to name matching when tun_dev is known")

    monkeypatch.setattr(dns_apply, "_run", no_ip_link)
    assert dns_apply._linux_nebula_interface("home-lab") == "home-lab"
    assert dns_apply._linux_nebula_interface("work") is None


def test_nm_unmanaged_conf_lists_the_tun_dev(monkeypatch):
    written = {}

    def fake_write(path, content):
        written[path] = content
        return False  # unchanged, so no NetworkManager reload

    monkeypatch.setattr(dns_apply, "_write_if_changed", fake_write)

    dns_apply._linux_nm_keep_off_nebula("home-lab")

    assert "unmanaged-devices=interface-name:nebula*;interface-name:home-lab\n" in written[
        dns_apply.LINUX_NM_UNMANAGED_CONF
    ]


def test_other_tun_devices_classify_as_nebula(monkeypatch):
    monkeypatch.setattr(linux_routing.os.path, "isdir", lambda p: False)
    monkeypatch.setattr(linux_routing.os.path, "exists", lambda p: p == "/sys/class/net/work/tun_flags")
    assert linux_routing._classify("work") == "nebula"
    assert linux_routing._classify("nebula1") == "nebula"
    assert linux_routing._classify("eth0") == "ethernet"
