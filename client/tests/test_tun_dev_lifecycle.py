"""
What run_poll_loop does with this instance's tun device over its lifetime (Linux):

- start with no config.yaml yet: no DNS clean-up at all - guessing "nebula1" removed
  another instance's DNS file (seen on a Debian VM, 2026-10-22);
- the network's device renamed: the old device's DNS file and nft table are removed,
  not left behind;
- loop stops while this node advertises routes: its nft table goes too.

The network, Nebula, DNS and routing calls are stubbed out.
"""
import threading

import pytest
import requests

from client import ncclient


def _config(dev: str) -> bytes:
    return f"tun:\n  dev: {dev}\nlisten:\n  port: 4242\n".encode()


class _Resp:
    def __init__(self, status=200, content=b"", etag=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.content = content
        self.text = content.decode(errors="replace")
        self.headers = {"ETag": f'"{etag}"'} if etag else {}

    def json(self):
        return {}


class _FakeProc:
    pid = 1

    def poll(self):
        return None


@pytest.fixture
def env(monkeypatch, tmp_path):
    calls = {"dns_remove": [], "routes": []}
    monkeypatch.setattr(ncclient.sys, "platform", "linux")
    monkeypatch.setattr(ncclient, "_start_nebula", lambda b, o: _FakeProc())
    monkeypatch.setattr(ncclient, "_stop_nebula", lambda p: None)
    import client.dns_apply as dns_apply
    monkeypatch.setattr(dns_apply, "remove_split_horizon_dns", lambda dev=None: calls["dns_remove"].append(dev) or True)
    monkeypatch.setattr(dns_apply, "apply_split_horizon_dns", lambda *a, **k: True)
    monkeypatch.setattr(dns_apply, "ensure_split_horizon_dns", lambda *a, **k: True)
    import client.exit_routing as exit_routing
    monkeypatch.setattr(exit_routing, "remove", lambda *a, **k: None)
    monkeypatch.setattr(exit_routing, "apply", lambda *a, **k: False)
    monkeypatch.setattr(exit_routing, "bind_to_uplink", lambda b, log=None: b)
    import client.linux_routing as linux_routing
    monkeypatch.setattr(linux_routing, "apply_routes", lambda routes, dev, debug_log=None: calls["routes"].append((list(routes), dev)))
    import client.token_store as token_store
    monkeypatch.setattr(token_store, "get_token", lambda: "the-token")
    import client.config as config
    monkeypatch.setattr(config, "load_settings", lambda: {"node_id": 7})
    for name in ("_maybe_check_for_updates", "_send_heartbeat"):
        monkeypatch.setattr(ncclient, name, lambda *a, **k: None)
    monkeypatch.setattr(ncclient, "_fetch_lighthouse_peers", lambda *a, **k: [])
    monkeypatch.setattr(ncclient, "_fetch_advertised_routes", lambda *a, **k: env_routes["routes"])
    env_routes = {"routes": []}
    return tmp_path, calls, env_routes


def _run(output_dir, configs: list[bytes]):
    """One poll per entry in configs (each a new ETag), then stop."""
    stop = threading.Event()
    served = []

    def get(url, **kw):
        if url.endswith("/api/device/config"):
            i = len(served)
            served.append(i)
            if i + 1 >= len(configs):
                stop.set()
            return _Resp(200, configs[min(i, len(configs) - 1)], etag=f"e{i}")
        return _Resp(404)

    original = requests.get
    requests.get = get
    try:
        ncclient.run_poll_loop("https://nc.example.invalid", str(output_dir), 1, "nebula", None, stop,
                               status_callback=lambda s, m: None, accept_dns=True)
    finally:
        requests.get = original


def test_no_dns_cleanup_at_start_without_a_config(env):
    out, calls, _ = env
    _run(out, [_config("nc-office")])
    assert calls["dns_remove"][:1] != [None], "start-up clean-up must not guess a device"
    assert None not in calls["dns_remove"]


def test_dns_cleanup_at_start_uses_the_device_from_the_config_on_disk(env):
    out, calls, _ = env
    (out / "config.yaml").write_bytes(_config("nc-office"))
    _run(out, [_config("nc-office")])
    assert calls["dns_remove"][0] == "nc-office"


def test_rename_removes_the_old_devices_dns_and_routing(env):
    out, calls, routes = env
    routes["routes"] = ["192.168.50.0/24"]
    _run(out, [_config("nc-old"), _config("nc-new")])
    assert "nc-old" in calls["dns_remove"]
    assert ([], "nc-old") in calls["routes"], "the old device's nft table must be deleted"


def test_stopping_removes_this_instances_nft_table(env):
    out, calls, routes = env
    routes["routes"] = ["192.168.50.0/24"]
    _run(out, [_config("nc-office"), _config("nc-office")])
    assert calls["routes"][-1] == ([], "nc-office")
