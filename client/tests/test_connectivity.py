"""client/connectivity.py and its pipe command (get_connectivity)."""
import subprocess
import sys

import pytest

from client import connectivity

CONFIG = """
pki:
  key: "[redacted]"
lighthouse:
  am_lighthouse: false
  hosts:
    - 10.99.0.1
    - 10.99.0.2
tun:
  dev: nebula7
"""


def test_parse_config_reads_device_and_lighthouses():
    assert connectivity.parse_config(CONFIG) == ("nebula7", ["10.99.0.1", "10.99.0.2"])


def test_parse_config_defaults_on_missing_or_bad_yaml():
    assert connectivity.parse_config("pki: {}\n") == ("nebula1", [])
    assert connectivity.parse_config("a: [unclosed") == ("nebula1", [])
    assert connectivity.parse_config("- a list\n") == ("nebula1", [])


def _completed(returncode, stdout):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_ping_parses_rtt_and_failure(monkeypatch):
    replies = iter([
        _completed(0, "Reply from 10.99.0.1: bytes=32 time=14ms TTL=64"),
        _completed(0, "Reply from 10.99.0.1: bytes=32 time<1ms TTL=64"),
        _completed(0, "64 bytes from 10.99.0.1: icmp_seq=1 ttl=64 time=3.25 ms"),
        _completed(1, "Request timed out."),
    ])
    monkeypatch.setattr(connectivity.subprocess, "run", lambda *a, **k: next(replies))
    assert connectivity.ping("10.99.0.1") == 14.0
    assert connectivity.ping("10.99.0.1") == 1.0
    assert connectivity.ping("10.99.0.1") == 3.25
    assert connectivity.ping("10.99.0.1") is None


def test_get_connectivity_pings_lighthouses_when_tunnel_has_address(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr(connectivity, "interface_ipv4", lambda dev: "10.99.0.5" if dev == "nebula7" else None)
    monkeypatch.setattr(connectivity, "ping", lambda ip: 12.4 if ip == "10.99.0.2" else None)

    result = connectivity.get_connectivity(str(tmp_path))

    assert result["overlay_ip"] == "10.99.0.5"
    assert result["interface_up"] is True
    assert result["tun_dev"] == "nebula7"
    assert result["lighthouses"] == [
        {"overlay_ip": "10.99.0.1", "reachable": False, "rtt_ms": None},
        {"overlay_ip": "10.99.0.2", "reachable": True, "rtt_ms": 12},
    ]


def test_get_connectivity_without_config_or_interface(tmp_path, monkeypatch):
    monkeypatch.setattr(connectivity, "interface_ipv4", lambda dev: None)
    monkeypatch.setattr(connectivity, "ping", lambda ip: (_ for _ in ()).throw(AssertionError("must not ping")))

    result = connectivity.get_connectivity(str(tmp_path))

    assert result["overlay_ip"] is None
    assert result["interface_up"] is False
    assert result["lighthouses"] == []


def test_get_connectivity_is_a_read_command():
    from client.windows import pipe_protocol as proto
    from client.windows import pipe_server

    commands = pipe_server._build_commands(pipe_server.ServiceHooks())
    assert commands[proto.CMD_GET_CONNECTIVITY][1] == pipe_server.READ


def test_interface_name_is_validated_before_reaching_a_shell(monkeypatch):
    monkeypatch.setattr(connectivity.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    assert connectivity.interface_ipv4(r"x'; Remove-Item C:\ -Recurse; '") is None
    assert connectivity.interface_ipv4("") is None


@pytest.mark.skipif(sys.platform != "win32", reason="GetAdaptersAddresses is Windows-only")
def test_windows_interface_ipv4_reads_adapters_natively():
    assert connectivity._windows_interface_ipv4("Loopback Pseudo-Interface 1") == "127.0.0.1"
    assert connectivity._windows_interface_ipv4("no-such-adapter-here") is None


def test_windows_interface_ipv4_falls_back_to_powershell(monkeypatch):
    monkeypatch.setattr(connectivity.sys, "platform", "win32")

    def broken(dev):
        raise OSError("GetAdaptersAddresses failed")

    monkeypatch.setattr(connectivity, "_windows_interface_ipv4", broken)
    monkeypatch.setattr(connectivity.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, "10.100.0.2\n", ""))
    assert connectivity.interface_ipv4("nebula1") == "10.100.0.2"
