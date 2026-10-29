"""
Following a server move (client/server_move.py): what makes a device switch, wait, or
stay put, and that the poll loop keeps Nebula up on a moved server's 410.
"""
import base64
import hashlib
import json
import threading
import time
from datetime import datetime, timezone

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from client import config, ncclient, server_move

OLD = "https://nebulacdr.net"
NEW = "https://beardedtek.nebulacdr.net"
FOREIGN = "https://nc.mycompany.com"


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _pub(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def _fp(pub_b64: str) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(base64.b64decode(pub_b64)).digest()).rstrip(b"=").decode()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None, microsecond=0).isoformat() + "Z"


OLD_KEY = Ed25519PrivateKey.generate()
NEW_KEY = Ed25519PrivateKey.generate()


def statement(new_url=NEW, key=OLD_KEY, new_key=NEW_KEY, switch_in=3600, expires_in=86400 * 365, move_id="m1", v=1):
    now = time.time()
    body = json.dumps({
        "v": v, "move_id": move_id, "old_url": OLD, "new_url": new_url, "new_key_fp": _fp(_pub(new_key)),
        "created_at": _iso(now), "switch_at": _iso(now + switch_in), "expires_at": _iso(now + expires_in),
    }, sort_keys=True, separators=(",", ":")).encode()
    return f"{_b64url(body)}.{_b64url(key.sign(body))}"


@pytest.fixture
def env(monkeypatch, tmp_path):
    """A settings.json with one network on OLD, pinned to OLD_KEY; the new server faked."""
    monkeypatch.setenv("NEBULA_COMMANDER_CONFIG_DIR", str(tmp_path))
    config.save_settings({"enrollments": [{
        "id": "net1", "server": OLD, "node_id": 7, "network_id": 3,
        "instance_key": _pub(OLD_KEY), "pinned_domain": "nebulacdr.net",
    }]})
    new_server = {"key": NEW_KEY, "node_id": 7, "network_id": 3, "proof_status": 200}

    class R:
        def __init__(self, status, data):
            self.status_code, self._data = status, data
            self.ok = 200 <= status < 300

        def json(self):
            return self._data

    def fake_post(url, json=None, headers=None, **kw):
        assert url.endswith("/api/device/move-proof")
        if new_server["proof_status"] != 200:
            return R(new_server["proof_status"], {})
        node = new_server["node_id"]
        msg = f"{server_move.PROOF_PREFIX}|{json['nonce']}|{node}|{json['new_url']}".encode()
        return R(200, {"public_key": _pub(new_server["key"]), "signature": _b64url(new_server["key"].sign(msg))})

    def fake_get(url, headers=None, **kw):
        assert url.endswith("/api/device/info")
        return R(200, {"node_id": new_server["node_id"], "network_id": new_server["network_id"]})

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.delenv("NCCLIENT_MOVE_FLOOR_SECONDS", raising=False)
    return new_server


def enrollment() -> dict:
    return config.find_enrollment(config.load_settings(), "net1")


def observe(tracker, header, now=None):
    switching = []
    result = tracker.observe(header, OLD, "tok", 7, lambda: switching.append(tracker.state), now=now)
    return result, switching


def test_switches_after_the_wait(env):
    t = server_move.MoveTracker("net1")
    header = statement(switch_in=3600)
    assert observe(t, header) == (None, [])
    assert t.state == "pending" and "beardedtek.nebulacdr.net" in t.notice()
    later = time.time() + 3601
    result, switching = observe(t, header, now=later)
    assert result == NEW and switching == ["switching"]
    e = enrollment()
    assert e["server"] == NEW and e["previous_server"] == OLD
    assert e["instance_key"] == _pub(NEW_KEY) and "pending_move" not in e


def test_foreign_domain_waits_at_least_a_day_whatever_the_server_says(env):
    t = server_move.MoveTracker("net1")
    header = statement(new_url=FOREIGN, switch_in=0)
    now = time.time()
    assert observe(t, header, now=now)[0] is None
    assert observe(t, header, now=now + 3 * 3600)[0] is None  # a same-domain move would be done by now
    assert enrollment()["pending_move"]["cross_domain"] is True
    assert "different provider" in t.notice()
    t._last_attempt = 0
    assert observe(t, header, now=now + 24 * 3600 + 1)[0] == FOREIGN


def test_ip_destination_counts_as_foreign(env):
    assert server_move.floor_seconds("nebulacdr.net", "https://203.0.113.5") == server_move.FOREIGN_FLOOR
    assert server_move.floor_seconds("nebulacdr.net", NEW) == server_move.SAME_DOMAIN_FLOOR


def test_statement_from_another_key_is_ignored(env):
    t = server_move.MoveTracker("net1")
    assert observe(t, statement(key=Ed25519PrivateKey.generate()), now=time.time() + 10 ** 6)[0] is None
    assert t.state == "failed" and "not signed" in t.error
    assert "pending_move" not in enrollment()


@pytest.mark.parametrize("kwargs,error", [
    ({"expires_in": -1}, "expired"),
    ({"new_url": "http://plain.example.com"}, "https"),
    ({"new_url": OLD}, "current server"),
    ({"v": 2}, "version"),
])
def test_bad_statements(env, kwargs, error):
    t = server_move.MoveTracker("net1")
    assert observe(t, statement(**kwargs))[0] is None
    assert error in t.error


def test_disappearing_statement_cancels(env):
    t = server_move.MoveTracker("net1")
    observe(t, statement())
    assert enrollment().get("pending_move")
    assert observe(t, None) == (None, [])
    assert "pending_move" not in enrollment() and t.notice() is None


def test_wrong_new_server_key_keeps_the_device_put(env):
    env["key"] = Ed25519PrivateKey.generate()  # not the key the statement names
    t = server_move.MoveTracker("net1")
    header = statement(switch_in=0)
    now = time.time() + 3601
    observe(t, header, now=time.time())
    assert observe(t, header, now=now)[0] is None
    assert "fingerprint" in t.error and enrollment()["server"] == OLD


def test_new_server_with_another_node_keeps_the_device_put(env):
    env["network_id"] = 99
    t = server_move.MoveTracker("net1")
    header = statement(switch_in=0)
    observe(t, header, now=time.time())
    assert observe(t, header, now=time.time() + 3601)[0] is None
    assert "different node or network" in t.error


def test_new_server_without_the_device_keys(env):
    env["proof_status"] = 401
    t = server_move.MoveTracker("net1")
    header = statement(switch_in=0)
    observe(t, header, now=time.time())
    assert observe(t, header, now=time.time() + 3601)[0] is None
    assert "device keys" in t.error


@pytest.mark.parametrize("policy,target,allowed", [
    ("none", NEW, False),
    ("same-domain", NEW, True),
    ("same-domain", FOREIGN, False),
    ("any", FOREIGN, True),
    (None, FOREIGN, True),
])
def test_move_policy(env, policy, target, allowed):
    settings = config.load_settings()
    if policy:
        settings["move_policy"] = policy
    config.save_settings(settings)
    t = server_move.MoveTracker("net1")
    observe(t, statement(new_url=target))
    assert (t.state == "pending") is allowed


def test_unpinned_network_never_moves(env):
    settings = config.load_settings()
    settings["enrollments"][0].pop("instance_key")
    config.save_settings(settings)
    t = server_move.MoveTracker("net1")
    assert observe(t, statement(switch_in=0), now=time.time() + 10 ** 6)[0] is None
    assert "no pinned" in t.error
    assert t.heartbeat_fields()["move_ready"] is False


def test_registrable_domain():
    rd = server_move.registrable_domain
    assert rd("beardedtek.nebulacdr.net") == "nebulacdr.net"
    assert rd("nc.example.co.uk") == "example.co.uk"
    assert rd("nebulacdr.net.evil.com") == "evil.com"
    assert rd("203.0.113.5") is None


def test_poll_loop_keeps_nebula_up_on_a_moved_servers_410(env, monkeypatch, tmp_path):
    """A moved-only server answers 410 + statement: Nebula keeps running on the last
    config and nothing is torn down (a 401 would delete config.yaml)."""
    out = tmp_path / "networks" / "net1"
    out.mkdir(parents=True)
    (out / "config.yaml").write_text("pki: {}\n")
    started = []

    class Proc:
        def poll(self):
            return None

    monkeypatch.setattr(ncclient, "_start_nebula", lambda *a, **k: started.append(1) or Proc())
    monkeypatch.setattr(ncclient, "_stop_nebula", lambda proc: None)
    import client.dns_apply as dns_apply
    for name in ("remove_split_horizon_dns", "apply_split_horizon_dns", "ensure_split_horizon_dns"):
        monkeypatch.setattr(dns_apply, name, lambda *a, **k: True)
    import client.token_store as token_store
    monkeypatch.setattr(token_store, "get_token", lambda eid=None: "tok")
    header = statement()

    class R:
        status_code, ok, text = 410, False, "moved"
        headers = {server_move.MOVE_HEADER: header}
        content = b""

    stop = threading.Event()
    calls = []

    def get(url, *a, **k):
        if url.endswith("/api/device/config"):
            calls.append(url)
            if len(calls) >= 2:
                stop.set()
            return R()
        raise requests.ConnectionError("no")

    monkeypatch.setattr(requests, "get", get)
    statuses = []
    ncclient.run_poll_loop(OLD, str(out), 1, "nebula", None, stop,
                           status_callback=lambda s, m: statuses.append((s, m)), enrollment_id="net1")
    assert (out / "config.yaml").exists() and started
    assert enrollment()["pending_move"]["new_url"] == NEW
    assert any("Moving to beardedtek.nebulacdr.net" in m for _, m in statuses)


def test_proxy_error_without_header_keeps_the_pending_move(env, monkeypatch, tmp_path):
    """Only a real answer (200/304) without the header cancels; a 502 from a proxy doesn't."""
    out = tmp_path / "networks" / "net1"
    out.mkdir(parents=True)
    monkeypatch.setattr(ncclient, "_start_nebula", lambda *a, **k: None)
    monkeypatch.setattr(ncclient, "_stop_nebula", lambda proc: None)
    import client.dns_apply as dns_apply
    for name in ("remove_split_horizon_dns", "apply_split_horizon_dns", "ensure_split_horizon_dns"):
        monkeypatch.setattr(dns_apply, name, lambda *a, **k: True)
    import client.token_store as token_store
    monkeypatch.setattr(token_store, "get_token", lambda eid=None: "tok")
    server_move.MoveTracker("net1").observe(statement(), OLD, "tok", 7, lambda: None)
    assert enrollment().get("pending_move")

    class R:
        status_code, ok, text, headers, content = 502, False, "bad gateway", {}, b""

    stop = threading.Event()

    def get(url, *a, **k):
        if url.endswith("/api/device/config"):
            stop.set()
            return R()
        raise requests.ConnectionError("no")

    monkeypatch.setattr(requests, "get", get)
    ncclient.run_poll_loop(OLD, str(out), 1, None, None, stop, status_callback=lambda s, m: None, enrollment_id="net1")
    assert enrollment().get("pending_move")
