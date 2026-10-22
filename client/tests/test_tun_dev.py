"""
The server names tun.dev after the network, so the Linux client must find its
interface by that name rather than by a "nebula" substring - and must not pick up
another ncclient's interface when a host is in more than one network.
"""
import os
import sys

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


@pytest.fixture
def sysfs(monkeypatch):
    """Fake /sys/class/net: call with {ifname: is_tun}."""
    def install(ifaces: dict[str, bool]):
        dirs = {f"/sys/class/net/{name}" for name in ifaces}
        files = {f"/sys/class/net/{name}/tun_flags" for name, tun in ifaces.items() if tun}
        def only_sysfs(real, known):
            # Everything outside /sys/class/net (e.g. config.yaml) stays real.
            return lambda p: p in known if str(p).startswith("/sys/class/net/") else real(p)

        monkeypatch.setattr("os.path.isdir", only_sysfs(os.path.isdir, dirs))
        monkeypatch.setattr("os.path.exists", only_sysfs(os.path.exists, files | dirs))
    return install


def test_interface_lookup_uses_tun_dev_not_the_nebula_substring(monkeypatch, sysfs):
    sysfs({"nc-home-lab": True, "nebula1": True})

    def no_ip_link(*a, **k):
        raise AssertionError("must not fall back to name matching when tun_dev is known")

    monkeypatch.setattr(dns_apply, "_run", no_ip_link)
    assert dns_apply._linux_nebula_interface("nc-home-lab") == "nc-home-lab"
    assert dns_apply._linux_nebula_interface("nc-work") is None


def test_interface_lookup_ignores_a_non_tun_interface(sysfs):
    sysfs({"eth0": False})
    assert dns_apply._linux_nebula_interface("eth0") is None


@pytest.fixture
def nm_conf(monkeypatch):
    written = {}

    def fake_write(path, content):
        written[path] = content
        return False  # unchanged, so no NetworkManager reload

    monkeypatch.setattr(dns_apply, "_write_if_changed", fake_write)
    return lambda: written[dns_apply.LINUX_NM_UNMANAGED_CONF]


def test_nm_unmanaged_conf_is_the_same_for_every_instance(nm_conf):
    dns_apply._linux_nm_keep_off_nebula()
    assert "unmanaged-devices=interface-name:nebula*;interface-name:nc-*\n" in nm_conf()


def test_foreign_interface(sysfs):
    sysfs({"eth0": False, "nc-home": True})
    assert linux_routing.is_foreign_interface("eth0")
    assert not linux_routing.is_foreign_interface("nc-home")
    assert not linux_routing.is_foreign_interface("nc-not-up-yet")


def test_routes_are_not_applied_to_a_non_tun_interface(monkeypatch, sysfs):
    sysfs({"eth0": False})
    calls = []
    monkeypatch.setattr(linux_routing, "_delete_table", lambda dev: calls.append("delete"))
    monkeypatch.setattr(linux_routing, "_set_ip_forward", lambda r: calls.append("forward"))
    monkeypatch.setattr(linux_routing, "_docker_forward_rules", lambda routes, dev, log: calls.append(("docker", routes)))

    linux_routing.apply_routes([{"route": "192.168.1.0/24"}], "eth0", debug_log=lambda m: None)

    assert calls == ["delete", ("docker", [])]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux-only guard")
def test_nebula_does_not_start_on_a_non_tun_interface(monkeypatch, tmp_path, sysfs, capsys):
    (tmp_path / "config.yaml").write_bytes(b"tun:\n  dev: eth0\n")
    sysfs({"eth0": False})

    def no_popen(*a, **k):
        raise AssertionError("nebula must not be started")

    monkeypatch.setattr(ncclient.subprocess, "Popen", no_popen)
    assert ncclient._start_nebula("nebula", str(tmp_path)) is None
    assert "tun.dev 'eth0' is an existing non-tun interface" in capsys.readouterr().err


def test_other_tun_devices_classify_as_nebula(sysfs):
    sysfs({"work": True, "eth0": False})
    assert linux_routing._classify("work") == "nebula"
    assert linux_routing._classify("nebula1") == "nebula"
    assert linux_routing._classify("nc-home") == "nebula"
    assert linux_routing._classify("eth0") == "ethernet"
