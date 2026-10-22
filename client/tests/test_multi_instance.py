"""
One host can run an ncclient per network, each on its own tun device. Host-wide state
must not let one instance undo another's:

- dnsmasq files are per instance (nebula-commander-<tun_dev>.conf); an instance only
  writes, verifies and removes its own.
- NetworkManager's unmanaged-devices drop-in is never removed at runtime: reloading
  NetworkManager without it lets NetworkManager take over the other instances' tun.
- The dnsmasq-mode drop-in goes only once no instance file is left.
- nftables tables and DOCKER-USER comments are per device.
- The instance on nebula1 removes what ncclient before 0.8.0 left (unsuffixed files,
  the shared table); no other instance touches those.
"""
import pytest

from client import dns_apply, linux_routing


@pytest.fixture
def etc(monkeypatch, tmp_path):
    nm = tmp_path / "NetworkManager"
    paths = {
        "LINUX_NM_DNSMASQ_CONF": nm / "dnsmasq.d" / "nebula-commander.conf",
        "LINUX_NM_DNS_MODE_CONF": nm / "conf.d" / "90-nebula-commander-dns.conf",
        "LINUX_NM_UNMANAGED_CONF": nm / "conf.d" / "91-nebula-commander-unmanaged.conf",
        "LINUX_DNSMASQ_CONF": tmp_path / "dnsmasq.d" / "nebula-commander.conf",
    }
    for name, path in paths.items():
        monkeypatch.setattr(dns_apply, name, str(path))
    reloads = []
    restarts = []
    monkeypatch.setattr(dns_apply, "_linux_networkmanager_available", lambda: True)
    monkeypatch.setattr(dns_apply, "_linux_nm_dns_property", lambda name: "dnsmasq")
    monkeypatch.setattr(dns_apply, "_linux_nm_reload", lambda what: reloads.append(what) or True)
    monkeypatch.setattr(dns_apply, "_linux_dnsmasq_restart", lambda: restarts.append(1) or True)
    return paths, reloads, restarts


def _nm_file(paths, dev):
    return paths["LINUX_NM_DNSMASQ_CONF"].parent / f"nebula-commander-{dev}.conf"


def test_nm_dnsmasq_instances_keep_their_own_files(etc):
    paths, reloads, _ = etc
    dns_apply._linux_nm_keep_off_nebula()
    assert dns_apply._linux_nm_dnsmasq_apply("nc-a", "a.example", ["10.1.0.1"])
    assert dns_apply._linux_nm_dnsmasq_apply("nc-b", "b.example", ["10.2.0.1"])

    # Each verifies only its own file, so neither re-applies (and reloads) every poll.
    reloads.clear()
    assert dns_apply._linux_nm_dnsmasq_verify("nc-a", "a.example", ["10.1.0.1"])
    assert dns_apply._linux_nm_dnsmasq_verify("nc-b", "b.example", ["10.2.0.1"])

    paths["LINUX_NM_DNS_MODE_CONF"].parent.mkdir(parents=True, exist_ok=True)
    paths["LINUX_NM_DNS_MODE_CONF"].write_text("[main]\ndns=dnsmasq\n")
    dns_apply._linux_nm_dnsmasq_remove("nc-a")
    assert not _nm_file(paths, "nc-a").exists()
    assert _nm_file(paths, "nc-b").exists()
    assert paths["LINUX_NM_DNS_MODE_CONF"].exists(), "nc-b still needs dnsmasq mode"
    assert paths["LINUX_NM_UNMANAGED_CONF"].exists()
    assert reloads == ["dns-full"], "no conf reload while another instance runs"

    dns_apply._linux_nm_dnsmasq_remove("nc-b")
    assert not paths["LINUX_NM_DNS_MODE_CONF"].exists()
    assert paths["LINUX_NM_UNMANAGED_CONF"].exists(), "only the package's uninstall removes it"
    assert reloads == ["dns-full", "conf"]


def test_only_the_nebula1_instance_removes_the_pre_0_8_0_file(etc):
    paths, _, _ = etc
    legacy = paths["LINUX_NM_DNSMASQ_CONF"]
    legacy.parent.mkdir(parents=True)
    legacy.write_text("server=/old.example/10.0.0.1\n")
    paths["LINUX_NM_DNS_MODE_CONF"].parent.mkdir(parents=True)
    paths["LINUX_NM_DNS_MODE_CONF"].write_text("[main]\ndns=dnsmasq\n")

    dns_apply._linux_nm_dnsmasq_remove("nc-a")
    assert legacy.exists()
    assert paths["LINUX_NM_DNS_MODE_CONF"].exists(), "the legacy file still needs dnsmasq mode"

    dns_apply._linux_nm_dnsmasq_remove("nebula1")
    assert not legacy.exists()
    assert not paths["LINUX_NM_DNS_MODE_CONF"].exists()


def test_dnsmasq_restarts_only_when_the_instance_file_changes(etc):
    paths, _, restarts = etc
    assert dns_apply._linux_dnsmasq_apply("nc-a", "a.example", ["10.1.0.1"])
    assert dns_apply._linux_dnsmasq_apply("nc-b", "b.example", ["10.2.0.1"])
    assert dns_apply._linux_dnsmasq_apply("nc-a", "a.example", ["10.1.0.1"])
    assert len(restarts) == 2

    assert dns_apply._linux_dnsmasq_verify("nc-a", "a.example", ["10.1.0.1"])
    assert not dns_apply._linux_dnsmasq_verify("nc-a", "a.example", ["10.9.0.1"])

    dns_apply._linux_dnsmasq_remove("nc-a")
    assert dns_apply._linux_dnsmasq_verify("nc-b", "b.example", ["10.2.0.1"])
    assert len(restarts) == 3


def test_remove_without_a_config_is_the_nebula1_instance(etc, monkeypatch):
    paths, _, _ = etc
    monkeypatch.setattr(dns_apply, "_linux_remove_legacy_files", lambda: None)
    monkeypatch.setattr(dns_apply, "_linux_resolved_remove", lambda dev: None)
    monkeypatch.setattr(dns_apply, "_linux_resolv_conf_remove", lambda: None)
    assert dns_apply._linux_dnsmasq_apply("nebula1", "old.example", ["10.0.0.1"])
    assert dns_apply._linux_dnsmasq_apply("nc-a", "a.example", ["10.1.0.1"])

    dns_apply._remove_linux(None)
    assert not (paths["LINUX_DNSMASQ_CONF"].parent / "nebula-commander-nebula1.conf").exists()
    assert dns_apply._linux_dnsmasq_verify("nc-a", "a.example", ["10.1.0.1"])


@pytest.mark.parametrize(
    ("dev", "table"),
    [("nebula1", "ncclient_routing_nebula1"), ("nc-home-lab", "ncclient_routing_nc_home_lab")],
)
def test_each_device_has_its_own_nft_table(dev, table):
    assert linux_routing.nft_table(dev) == table
    script = linux_routing._build_nft_script([{"route": "192.168.1.0/24"}], dev, None)
    assert script.startswith(f"table inet {table} {{\n")


def test_only_the_nebula1_instance_deletes_the_pre_0_8_0_table(monkeypatch):
    deleted = []
    monkeypatch.setattr(linux_routing.subprocess, "run", lambda argv, **kw: deleted.append(argv[-1]))
    linux_routing._delete_table("nc-a")
    assert deleted == ["ncclient_routing_nc_a"]
    deleted.clear()
    linux_routing._delete_table("nebula1")
    assert deleted == ["ncclient_routing_nebula1", "ncclient_routing"]
