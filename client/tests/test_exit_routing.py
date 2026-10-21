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
    assert plan == er.ExitPlan(tun_dev="nebula1", listen_port=4242, route_v6=True, listen_host="0.0.0.0")
    assert er.plan_from_config(CONFIG_V4_ONLY).route_v6 is False
    assert er.plan_from_config(CONFIG_NO_EXIT) is None
    assert er.plan_from_config(b"not: [valid") is None


def test_plan_rejects_a_tun_dev_that_is_not_interface_shaped():
    assert er.plan_from_config(CONFIG.replace(b"dev: nebula1", b"dev: 'eth0; rm -rf /'")) is None


# --- Linux commands ---------------------------------------------------------------

def _rules(cmds, fam):
    return [c for c in cmds if c[1] == fam and c[2] == "rule"]


def test_linux_commands_allow_lan_full_tunnel():
    cmds = er.linux_commands(er.plan_from_config(CONFIG), [4242], True, [], [])
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
    cmds = er.linux_commands(er.plan_from_config(CONFIG_V4_ONLY), [4242], True, [], [])
    v6_routes = [c for c in cmds if c[1] == "-6" and c[2] == "route"]
    assert v6_routes == [["ip", "-6", "route", "replace", "unreachable", "default", "metric",
                          str(er.KILL_SWITCH_METRIC), "table", "52042"]]
    assert _rules(cmds, "-6"), "IPv6 must still be policy-routed into the blocking table"


def test_linux_commands_strict_lan_keeps_only_overlay_and_dhcp_local():
    cmds = er.linux_commands(er.plan_from_config(CONFIG), [4242], False, ["10.100.0.0/24"], [])
    local_v4 = [c for c in _rules(cmds, "-4") if c[5] == "32741"]
    assert ["ip", "-4", "rule", "add", "pref", "32741", "to", "10.100.0.0/24", "lookup", "main"] in local_v4
    assert ["ip", "-4", "rule", "add", "pref", "32741", "ipproto", "udp", "dport", "67", "lookup", "main"] in local_v4
    assert not any("suppress_prefixlength" in c for c in cmds)
    local_v6 = [c for c in _rules(cmds, "-6") if c[5] == "32741"]
    assert {c[7] for c in local_v6} == {"fe80::/10", "ff00::/8"}


def test_linux_commands_strict_lan_keeps_replies_to_inbound_connections_local():
    """LAN blocked used to cut every inbound LAN connection (SSH into a Debian VM dropped):
    replies leave from the address the connection came in on, so that source stays local."""
    cmds = er.linux_commands(er.plan_from_config(CONFIG), [4242], False, [], [],
                             local_v4=("192.168.3.55",), local_v6=("2001:db8:1::55",))
    assert ["ip", "-4", "rule", "add", "pref", "32741", "from", "192.168.3.55", "lookup", "main"] in cmds
    assert ["ip", "-6", "rule", "add", "pref", "32741", "from", "2001:db8:1::55", "lookup", "main"] in cmds
    allowed = er.linux_commands(er.plan_from_config(CONFIG), [4242], True, [], [], local_v4=("192.168.3.55",))
    assert not any("from" in c for c in allowed), "LAN allowed: suppress_prefixlength already covers it"


def test_own_addresses_skip_loopback_tunnels_and_link_local(monkeypatch):
    out = (
        "1: lo    inet 127.0.0.1/8 scope host lo\n"
        "2: enp0s3    inet 192.168.3.55/24 brd 192.168.3.255 scope global dynamic enp0s3\n"
        "2: enp0s3    inet6 2001:db8:1::55/64 scope global dynamic\n"
        "2: enp0s3    inet6 fe80::a00:27ff:fe00:1/64 scope link\n"
        "3: docker0    inet 172.17.0.1/16 scope global docker0\n"
        "5: nebula1    inet 10.100.0.31/24 scope global nebula1\n"
        "6: veth1@if5    inet 10.9.0.1/24 scope global veth1\n"
    )
    monkeypatch.setattr(er, "_run", lambda cmd, **kw: _ok(out))
    monkeypatch.setattr(er.os.path, "exists", lambda p: p == "/sys/class/net/nebula1/tun_flags")
    assert er._linux_own_addresses() == (("10.9.0.1", "172.17.0.1", "192.168.3.55"), ("2001:db8:1::55",))


def test_linux_commands_without_ipv6_or_tun():
    plan = er.plan_from_config(CONFIG)
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
# Nebula is bound to the uplink's address (strong host model) instead of /32 bypass
# routes, which had to exempt the lighthouses, the exit gateway and the control server
# entirely: measured on Windows 11, `tracert cloud.nebulacdr.net` went around the exit.

def _windows(monkeypatch, uplink=(7, "192.168.1.50"), stdout="MISSING:0"):
    scripts = []
    monkeypatch.setattr(er.sys, "platform", "win32")
    monkeypatch.setattr(er, "_windows_uplink", lambda tun: uplink)
    monkeypatch.setattr(er, "_windows_lan_prefix", lambda idx: "192.168.1.0/24")
    monkeypatch.setattr(er, "_powershell", lambda s, **kw: scripts.append(s) or _ok(stdout))
    return scripts


def test_bind_to_uplink_sets_listen_host_only_with_an_exit_route(monkeypatch):
    _windows(monkeypatch)
    bound = er.bind_to_uplink(CONFIG)
    assert er.plan_from_config(bound).listen_host == "192.168.1.50"
    assert er.bind_to_uplink(bound) == bound, "already bound: unchanged bytes, no restart"
    assert er.bind_to_uplink(CONFIG_NO_EXIT) == CONFIG_NO_EXIT
    # Exit node rejected while bound: back to 0.0.0.0, so the binding can't go stale.
    stale = er.with_listen_host(CONFIG_NO_EXIT + b"listen: {host: 0.0.0.0, port: 4242}\n", "192.168.1.50")
    assert b"0.0.0.0" in er.bind_to_uplink(stale) and b"192.168.1.50" not in er.bind_to_uplink(stale)
    monkeypatch.setattr(er, "_windows_uplink", lambda tun: None)
    assert er.bind_to_uplink(CONFIG) == CONFIG, "offline: left alone, next poll retries"
    monkeypatch.setattr(er.sys, "platform", "linux")
    assert er.bind_to_uplink(CONFIG) == CONFIG


def test_windows_apply_requires_nebula_bound_to_the_uplink(monkeypatch, tmp_path):
    scripts = _windows(monkeypatch)
    assert er.apply(CONFIG_V4_ONLY, str(tmp_path)) is False, "still bound to 0.0.0.0"
    assert scripts == []
    bound = er.with_listen_host(CONFIG_V4_ONLY, "192.168.1.50")
    assert er.apply(bound, str(tmp_path)) is True
    assert "New-NetRoute" not in scripts[-1], "no bypass routes any more"
    assert f"New-NetFirewallRule -DisplayName '{er.WINDOWS_V6_BLOCK_RULE}'" in scripts[-1]
    # The uplink address changed: not bound to the new one yet.
    monkeypatch.setattr(er, "_windows_uplink", lambda tun: (9, "10.0.0.7"))
    assert er.apply(bound, str(tmp_path)) is False


def test_windows_lan_block_and_removal(monkeypatch, tmp_path):
    scripts = _windows(monkeypatch)
    bound = er.with_listen_host(CONFIG, "192.168.1.50")
    assert er.apply(bound, str(tmp_path), allow_lan=False) is True
    assert "New-NetRoute -DestinationPrefix '192.168.1.0/24' -InterfaceAlias 'nebula1'" in scripts[-1]
    assert "New-NetFirewallRule" not in scripts[-1], "gateway routes ::/0: no IPv6 block"
    state = json.loads((tmp_path / er.WINDOWS_STATE_FILE).read_text())
    assert state["lan"] == "192.168.1.0/24"
    er.apply(CONFIG_NO_EXIT, str(tmp_path))
    assert "Remove-NetRoute -DestinationPrefix '192.168.1.0/24'" in scripts[-1]
    assert not (tmp_path / er.WINDOWS_STATE_FILE).exists()


def test_windows_removes_bypass_routes_left_by_the_previous_build(monkeypatch, tmp_path):
    scripts = _windows(monkeypatch)
    old = {"tun_dev": "nebula1", "if_index": 7, "gateway": "192.168.1.1",
           "routes": ["203.0.113.10"], "lan": None, "block_v6": False}
    (tmp_path / er.WINDOWS_STATE_FILE).write_text(json.dumps(old))
    er.apply(er.with_listen_host(CONFIG, "192.168.1.50"), str(tmp_path))
    assert "Remove-NetRoute -DestinationPrefix '203.0.113.10/32' -InterfaceIndex 7 -NextHop '192.168.1.1'" in scripts[-1]
    assert "routes" not in json.loads((tmp_path / er.WINDOWS_STATE_FILE).read_text())


def test_windows_success_is_judged_by_state_present_not_exit_code(monkeypatch, tmp_path):
    """Measured on Windows 11: re-asserting an existing route makes New-NetRoute fail, and
    powershell -Command then exits 1 - which used to be reported as a routing failure."""
    _windows(monkeypatch)
    bound = er.with_listen_host(CONFIG_V4_ONLY, "192.168.1.50")
    monkeypatch.setattr(er, "_powershell", lambda s, **kw: subprocess.CompletedProcess([], 1, "MISSING:0", "exists"))
    assert er.apply(bound, str(tmp_path)) is True
    monkeypatch.setattr(er, "_powershell", lambda s, **kw: subprocess.CompletedProcess([], 0, "MISSING:1", ""))
    assert er.apply(bound, str(tmp_path)) is False
    assert er.windows_script({"if_index": 7, "block_v6": True}, None, "nebula1").rstrip().endswith("exit 0")


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
