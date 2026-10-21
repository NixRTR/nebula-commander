"""
Tests for client/exit_routing.py - full-tunnel routing on a node that uses an exit
node, without routing Nebula's own UDP into its own tunnel (the loop that made exit
nodes unusable whenever the gateway wasn't on the consumer's LAN).
"""
import json
import subprocess

import pytest

from client import exit_routing as er

CONFIG = b"""
static_host_map:
  "10.100.0.30": ["203.0.113.10:4242"]
  "10.100.0.1": ["198.51.100.20:4242", "[2001:db8::1]:4242"]
listen: {host: 0.0.0.0, port: 4242}
tun:
  dev: nebula1
  unsafe_routes:
  - route: 0.0.0.0/0
    via: 10.100.0.30
    install: false
  - route: ::/0
    via: 10.100.0.30
    install: false
"""
CONFIG_V4_ONLY = CONFIG.replace(b"  - route: ::/0\n    via: 10.100.0.30\n    install: false\n", b"")
CONFIG_NO_EXIT = b"tun: {dev: nebula1, unsafe_routes: [{route: 192.168.1.0/24, via: 10.100.0.17}]}\n"


def _ok(stdout=""):
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


# --- plan --------------------------------------------------------------------------

def test_plan_from_config():
    plan = er.plan_from_config(CONFIG)
    assert plan == er.ExitPlan(
        tun_dev="nebula1", listen_port=4242, route_v6=True, underlay_ips=("198.51.100.20", "203.0.113.10")
    )
    assert er.plan_from_config(CONFIG_V4_ONLY).route_v6 is False
    assert er.plan_from_config(CONFIG_NO_EXIT) is None
    assert er.plan_from_config(b"not: [valid") is None
    assert er.plan_from_config(CONFIG, resolve=False).underlay_ips == ()


def test_plan_rejects_a_tun_dev_that_is_not_interface_shaped():
    assert er.plan_from_config(CONFIG.replace(b"dev: nebula1", b"dev: 'eth0; rm -rf /'")) is None


# --- Linux commands ---------------------------------------------------------------

def _rules(cmds, fam):
    return [c for c in cmds if c[1] == fam and c[2] == "rule"]


def test_linux_commands_allow_lan_full_tunnel():
    cmds = er.linux_commands(er.plan_from_config(CONFIG, resolve=False), [4242], True, [], [])
    for fam in ("-4", "-6"):
        rules = _rules(cmds, fam)
        assert rules[0] == ["ip", fam, "rule", "add", "pref", "32740", "ipproto", "udp", "sport", "4242", "lookup", "main"]
        assert ["ip", fam, "rule", "add", "pref", "32741", "lookup", "main", "suppress_prefixlength", "0"] in rules
        assert rules[-1] == ["ip", fam, "rule", "add", "pref", "32742", "lookup", "52042"]
    routes = [c for c in cmds if c[2] == "route"]
    assert ["ip", "-4", "route", "replace", "default", "dev", "nebula1", "table", "52042"] in routes
    assert ["ip", "-6", "route", "replace", "default", "dev", "nebula1", "table", "52042"] in routes
    # kill switch under both
    for fam in ("-4", "-6"):
        assert ["ip", fam, "route", "replace", "unreachable", "default", "metric", str(er.KILL_SWITCH_METRIC),
                "table", "52042"] in routes


def test_linux_commands_block_ipv6_when_gateway_has_no_v6_route():
    cmds = er.linux_commands(er.plan_from_config(CONFIG_V4_ONLY, resolve=False), [4242], True, [], [])
    v6_routes = [c for c in cmds if c[1] == "-6" and c[2] == "route"]
    assert v6_routes == [["ip", "-6", "route", "replace", "unreachable", "default", "metric",
                          str(er.KILL_SWITCH_METRIC), "table", "52042"]]
    assert _rules(cmds, "-6"), "IPv6 must still be policy-routed into the blocking table"


def test_linux_commands_strict_lan_keeps_only_overlay_and_dhcp_local():
    cmds = er.linux_commands(er.plan_from_config(CONFIG, resolve=False), [4242], False, ["10.100.0.0/24"], [])
    local_v4 = [c for c in _rules(cmds, "-4") if c[5] == "32741"]
    assert ["ip", "-4", "rule", "add", "pref", "32741", "to", "10.100.0.0/24", "lookup", "main"] in local_v4
    assert ["ip", "-4", "rule", "add", "pref", "32741", "ipproto", "udp", "dport", "67", "lookup", "main"] in local_v4
    assert not any("suppress_prefixlength" in c for c in cmds)
    local_v6 = [c for c in _rules(cmds, "-6") if c[5] == "32741"]
    assert {c[7] for c in local_v6} == {"fe80::/10", "ff00::/8"}


def test_linux_commands_without_ipv6_or_tun():
    plan = er.plan_from_config(CONFIG, resolve=False)
    assert not any(c[1] == "-6" for c in er.linux_commands(plan, [4242], True, [], [], ipv6=False))
    no_tun = er.linux_commands(plan, [4242], True, [], [], tun_present=False)
    assert not any("dev" in c for c in no_tun if c[2] == "route"), "only the kill switch until the device exists"


def test_nebula_ports_from_ss(monkeypatch):
    out = (
        'UNCONN 0 0 0.0.0.0:5353 0.0.0.0:* users:(("avahi",pid=11,fd=12))\n'
        'UNCONN 0 0 [::]:41641 [::]:* users:(("nebula",pid=4321,fd=8))\n'
        'UNCONN 0 0 0.0.0.0:4243 0.0.0.0:* users:(("nebula",pid=999,fd=8))\n'
        'UNCONN 0 0 0.0.0.0:51820 0.0.0.0:* users:(("renamed-neb",pid=77,fd=8))\n'
    )
    monkeypatch.setattr(er, "_run", lambda cmd, **kw: _ok(out))
    assert er._linux_nebula_ports(4321) == [4243, 41641]
    assert er._linux_nebula_ports(77) == [4243, 41641, 51820], "our own pid counts even if renamed"


def test_every_nebula_on_the_host_is_exempted(linux_host, monkeypatch):
    """Another network's nebula (its own ncclient) must not be routed into this exit
    tunnel - measured: it lost its lighthouse when only this node's port was exempted."""
    monkeypatch.setattr(er, "_linux_nebula_ports", lambda pid: [4242, 4243])
    er.apply(CONFIG, "/tmp/x")
    sport_rules = [c for c in linux_host.calls if "sport" in c]
    assert {(c[1], c[c.index("sport") + 1]) for c in sport_rules} == {
        ("-4", "4242"), ("-4", "4243"), ("-6", "4242"), ("-6", "4243")
    }
    # A third nebula starting later changes the set: re-applied on the next call.
    monkeypatch.setattr(er, "_linux_nebula_ports", lambda pid: [4242, 4243, 4244])
    linux_host.calls.clear()
    er.apply(CONFIG, "/tmp/x")
    assert any("4244" in c for c in linux_host.calls)


class _FakeIp:
    """Records ip(8) calls and answers the presence checks like a real host would."""

    def __init__(self):
        self.calls = []
        self.table = ""
        self.rules = ""

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[2:4] == ["route", "show"]:
            return _ok(self.table)
        if cmd[2:4] == ["rule", "show"]:
            return _ok(self.rules)
        if cmd[2:4] == ["rule", "del"]:
            return subprocess.CompletedProcess(cmd, 2, "", "no such rule")
        if cmd[2:4] == ["route", "replace"]:
            self.table += " ".join(cmd[4:]) + "\n"
        if cmd[2:4] == ["rule", "add"]:
            self.rules += " ".join(cmd[4:]) + "\n"
        return _ok()


@pytest.fixture
def linux_host(monkeypatch):
    fake = _FakeIp()
    monkeypatch.setattr(er, "_run", fake)
    monkeypatch.setattr(er.os.path, "isdir", lambda p: p == "/sys/class/net/nebula1")
    monkeypatch.setattr(er, "_linux_ipv6_enabled", lambda: True)
    monkeypatch.setattr(er, "_linux_applied", None)
    monkeypatch.setattr(er.sys, "platform", "linux")
    return fake


def test_linux_apply_is_idempotent(linux_host):
    assert er.apply(CONFIG, "/tmp/x") is True
    adds = [c for c in linux_host.calls if c[0] == "ip" and c[3] in ("add", "replace")]
    assert adds
    linux_host.calls.clear()
    assert er.apply(CONFIG, "/tmp/x") is True
    assert not [c for c in linux_host.calls if c[0] == "ip" and c[3] in ("add", "replace", "del", "flush")], "unchanged = no churn"


def test_linux_apply_reinstalls_when_the_route_vanished(linux_host):
    er.apply(CONFIG, "/tmp/x")
    linux_host.table = ""  # nebula restarted: the kernel dropped the dev route
    linux_host.calls.clear()
    er.apply(CONFIG, "/tmp/x")
    assert ["ip", "-4", "route", "replace", "default", "dev", "nebula1", "table", "52042"] in linux_host.calls


def test_linux_apply_undoes_everything_on_any_failure(linux_host, monkeypatch):
    def failing(cmd, **kw):
        if cmd[:3] == ["ip", "-6", "route"] and cmd[3] == "replace":
            linux_host.calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 2, "", "boom")
        return linux_host(cmd, **kw)

    monkeypatch.setattr(er, "_run", failing)
    assert er.apply(CONFIG, "/tmp/x") is False
    assert er._linux_applied is None
    after_failure = linux_host.calls[linux_host.calls.index(next(c for c in linux_host.calls if c[0] == "ip" and c[1] == "-6" and c[3] == "replace")):]
    assert any(c[2:4] == ["rule", "del"] for c in after_failure)


def test_linux_apply_without_exit_route_only_removes_what_it_installed(linux_host):
    linux_host.calls.clear()
    er.apply(CONFIG_NO_EXIT, "/tmp/x")
    assert linux_host.calls == [], "nothing installed yet: no cleanup churn on every poll"
    er.apply(CONFIG, "/tmp/x")
    linux_host.calls.clear()
    er.apply(CONFIG_NO_EXIT, "/tmp/x")
    assert any(c[2:4] == ["rule", "del"] for c in linux_host.calls)
    assert ["ip", "-4", "route", "flush", "table", "52042"] in linux_host.calls


def test_linux_port_zero_without_known_port_does_not_install(linux_host, monkeypatch):
    monkeypatch.setattr(er, "_linux_nebula_ports", lambda pid: [])
    assert er.apply(CONFIG.replace(b"port: 4242", b"port: 0"), "/tmp/x", nebula_pid=1) is False
    assert not any(c[3] == "add" for c in linux_host.calls if len(c) > 3)


# --- Windows ------------------------------------------------------------------------

def test_windows_script_adds_bypass_routes_lan_and_v6_block():
    state = {"if_index": 7, "gateway": "192.168.1.1", "routes": ["203.0.113.10"], "lan": "192.168.1.0/24", "block_v6": True}
    script = er.windows_script(state, None, "nebula1")
    assert "New-NetRoute -DestinationPrefix '203.0.113.10/32' -InterfaceIndex 7 -NextHop '192.168.1.1'" in script
    assert "-PolicyStore ActiveStore" in script
    assert "New-NetRoute -DestinationPrefix '192.168.1.0/24' -InterfaceAlias 'nebula1'" in script
    assert f"New-NetFirewallRule -DisplayName '{er.WINDOWS_V6_BLOCK_RULE}'" in script
    assert "Remove-" not in script


def test_windows_script_removes_previous_state():
    old = {"if_index": 3, "gateway": "10.0.0.1", "routes": ["203.0.113.10"], "lan": None, "block_v6": True}
    script = er.windows_script({}, old, "nebula1")
    assert "Remove-NetRoute -DestinationPrefix '203.0.113.10/32' -InterfaceIndex 3 -NextHop '10.0.0.1'" in script
    assert f"Remove-NetFirewallRule -DisplayName '{er.WINDOWS_V6_BLOCK_RULE}'" in script
    assert "New-" not in script


def test_windows_apply_tracks_state_and_removes_exactly(monkeypatch, tmp_path):
    scripts = []
    monkeypatch.setattr(er.sys, "platform", "win32")
    monkeypatch.setattr(er, "_windows_default_gateway", lambda tun: (7, "192.168.1.1"))
    monkeypatch.setattr(er, "_powershell", lambda s, **kw: scripts.append(s) or _ok("MISSING:0"))
    monkeypatch.setattr(er, "_resolve_ipv4", lambda host: [host])

    assert er.apply(CONFIG_V4_ONLY, str(tmp_path)) is True
    state = json.loads((tmp_path / er.WINDOWS_STATE_FILE).read_text())
    assert state["routes"] == ["198.51.100.20", "203.0.113.10"] and state["block_v6"] is True
    assert "198.51.100.20/32" in scripts[-1]

    # Gateway changed (laptop moved networks): old routes removed, new ones added.
    monkeypatch.setattr(er, "_windows_default_gateway", lambda tun: (9, "10.0.0.1"))
    er.apply(CONFIG_V4_ONLY, str(tmp_path))
    assert "Remove-NetRoute -DestinationPrefix '203.0.113.10/32' -InterfaceIndex 7 -NextHop '192.168.1.1'" in scripts[-1]
    assert "-InterfaceIndex 9 -NextHop '10.0.0.1'" in scripts[-1]

    er.apply(CONFIG_NO_EXIT, str(tmp_path))
    assert "Remove-NetRoute" in scripts[-1] and "New-NetRoute" not in scripts[-1]
    assert not (tmp_path / er.WINDOWS_STATE_FILE).exists()


def test_windows_route_v6_through_exit_skips_the_block(monkeypatch, tmp_path):
    scripts = []
    monkeypatch.setattr(er.sys, "platform", "win32")
    monkeypatch.setattr(er, "_windows_default_gateway", lambda tun: (7, "192.168.1.1"))
    monkeypatch.setattr(er, "_powershell", lambda s, **kw: scripts.append(s) or _ok("MISSING:0"))
    monkeypatch.setattr(er, "_resolve_ipv4", lambda host: [host])
    er.apply(CONFIG, str(tmp_path))
    assert "New-NetFirewallRule" not in scripts[-1]


def test_windows_success_is_judged_by_routes_present_not_exit_code(monkeypatch, tmp_path):
    """Measured on Windows 11: re-asserting an existing route makes New-NetRoute fail, and
    powershell -Command then exits 1 - which used to be reported as a routing failure."""
    monkeypatch.setattr(er.sys, "platform", "win32")
    monkeypatch.setattr(er, "_windows_default_gateway", lambda tun: (7, "192.168.1.1"))
    monkeypatch.setattr(er, "_resolve_ipv4", lambda host: [host])
    monkeypatch.setattr(er, "_powershell", lambda s, **kw: subprocess.CompletedProcess([], 1, "MISSING:0\n", "exists"))
    assert er.apply(CONFIG_V4_ONLY, str(tmp_path)) is True
    monkeypatch.setattr(er, "_powershell", lambda s, **kw: subprocess.CompletedProcess([], 0, "MISSING:2\n", ""))
    assert er.apply(CONFIG_V4_ONLY, str(tmp_path)) is False
    script = er.windows_script({"if_index": 7, "gateway": "192.168.1.1", "routes": ["203.0.113.10"]}, None, "nebula1")
    assert "Get-NetRoute -DestinationPrefix \"$ip/32\" -InterfaceIndex 7" in script and script.rstrip().endswith("exit 0")


def test_apply_never_raises(monkeypatch):
    monkeypatch.setattr(er, "plan_from_config", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    assert er.apply(CONFIG, "/tmp/x") is False


# --- settings -------------------------------------------------------------------------

def test_exit_allow_lan_is_settable_and_must_be_bool(monkeypatch):
    from client import service_api

    saved = {}
    monkeypatch.setattr(service_api, "load_settings", lambda: {})
    monkeypatch.setattr(service_api, "save_settings", lambda s: saved.update(s))
    service_api.set_settings({"exit_allow_lan": False})
    assert saved == {"exit_allow_lan": False}
    with pytest.raises(service_api.ServiceApiError):
        service_api.set_settings({"exit_allow_lan": "no"})
