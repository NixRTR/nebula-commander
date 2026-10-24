"""A gateway's forwarded traffic leaves by the uplink, not by this host's own exit node.

Found on the Debian VM: an office exit gateway that also used an exit node in another
network routed the office's traffic into that other tunnel (table 52042) without NAT."""
import subprocess

from client import linux_routing


class _R:
    def __init__(self, rc):
        self.returncode, self.stdout, self.stderr = rc, "", ""


def _record(monkeypatch, existing=0):
    calls = []
    left = {"-4": existing, "-6": existing}

    def run(argv, **kw):
        calls.append(argv[1:])
        if argv[1:4] == [argv[1], "rule", "del"]:
            fam = argv[1]
            if left[fam]:
                left[fam] -= 1
                return _R(0)
            return _R(2)
        return _R(0)

    monkeypatch.setattr(linux_routing, "_which", lambda n: n)
    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_on_adds_iif_rule_for_both_families(monkeypatch):
    calls = _record(monkeypatch)
    linux_routing._set_gateway_rule("nc-office", True)
    adds = [c for c in calls if c[1:3] == ["rule", "add"]]
    assert adds == [
        [fam, "rule", "add", "pref", "32739", "iif", "nc-office", "lookup", "main"] for fam in ("-4", "-6")
    ]


def test_off_removes_every_copy_and_adds_none(monkeypatch):
    calls = _record(monkeypatch, existing=2)
    linux_routing._set_gateway_rule("nc-office", False)
    assert not [c for c in calls if c[1:3] == ["rule", "add"]]
    assert len([c for c in calls if c[:3] == ["-4", "rule", "del"]]) == 3  # 2 removed + 1 failing


def test_apply_routes_sets_and_clears_the_rule(monkeypatch):
    seen = []
    monkeypatch.setattr(linux_routing, "_set_gateway_rule", lambda dev, on: seen.append((dev, on)))
    monkeypatch.setattr(linux_routing, "_delete_table", lambda dev: None)
    monkeypatch.setattr(linux_routing, "_docker_forward_rules", lambda *a: None)
    monkeypatch.setattr(linux_routing, "_set_ip_forward", lambda *a: None)
    monkeypatch.setattr(linux_routing, "is_foreign_interface", lambda d: False)
    monkeypatch.setattr(linux_routing.shutil, "which", lambda n: n)
    monkeypatch.setattr(linux_routing, "_default_route_iface", lambda: "eth0")
    monkeypatch.setattr(linux_routing, "_which", lambda n: n)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R(0))
    linux_routing.apply_routes([{"route": "0.0.0.0/0"}], "nc-office")
    linux_routing.apply_routes([], "nc-office")
    assert seen == [("nc-office", True), ("nc-office", False)]
