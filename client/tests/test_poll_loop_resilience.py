"""
run_poll_loop under the two failure modes that matter for a running node:

- the server can't be reached (or returns a non-auth error) - e.g. the first poll after
  a reboot during a server outage: Nebula must still start from the last config.yaml
  on disk, instead of the node staying offline until the server is back;
- the server rejects the device token (401: revoked, deleted, or re-enrolled
  elsewhere): Nebula must be stopped and config.yaml (which holds the private key)
  deleted - and the loop must not hot-loop retrying the same rejected token.

The network, the Nebula process and DNS changes are stubbed out.
"""
import threading

import pytest
import requests

from client import ncclient


class _FakeProc:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None


@pytest.fixture
def loop_env(monkeypatch, tmp_path):
    started, stopped = [], []

    def fake_start(nebula_bin, output_dir):
        proc = _FakeProc()
        started.append(proc)
        return proc

    def fake_stop(proc):
        if proc is not None:
            proc.stopped = True
            stopped.append(proc)

    monkeypatch.setattr(ncclient, "_start_nebula", fake_start)
    monkeypatch.setattr(ncclient, "_stop_nebula", fake_stop)
    import client.dns_apply as dns_apply
    for name in ("remove_split_horizon_dns", "apply_split_horizon_dns", "ensure_split_horizon_dns"):
        monkeypatch.setattr(dns_apply, name, lambda *a, **k: True)
    import client.token_store as token_store
    monkeypatch.setattr(token_store, "get_token", lambda: "the-token")
    import client.config as config
    monkeypatch.setattr(config, "load_settings", lambda: {"node_id": None})
    return tmp_path, started, stopped


def _run(output_dir, get, *, polls: int = 0, seconds: float = 0, service: bool = True):
    """Run the loop with requests.get replaced by `get`, stopping after `polls` calls
    or (if given) after `seconds` of wall time, whichever comes first."""
    stop = threading.Event()
    calls = []
    statuses = []
    if seconds:
        threading.Timer(seconds, stop.set).start()

    def counting_get(*args, **kwargs):
        calls.append(args[0])
        if polls and len(calls) >= polls:
            stop.set()
        return get(*args, **kwargs)

    original = requests.get
    requests.get = counting_get
    try:
        ncclient.run_poll_loop(
            "https://nc.example.invalid", str(output_dir), 1, "nebula", None, stop,
            status_callback=(lambda state, msg: statuses.append((state, msg))) if service else None,
        )
    finally:
        requests.get = original
    return calls, statuses


def test_server_unreachable_starts_nebula_from_last_config(loop_env):
    out, started, _ = loop_env
    (out / "config.yaml").write_text("pki: {}\n")

    def unreachable(*a, **k):
        raise requests.ConnectionError("connection refused")

    _, statuses = _run(out, unreachable, polls=1)
    assert len(started) == 1
    assert any("last known config" in msg for _, msg in statuses)


def test_server_error_status_also_starts_nebula_from_last_config(loop_env):
    out, started, _ = loop_env
    (out / "config.yaml").write_text("pki: {}\n")

    class R:
        status_code = 502
        ok = False
        text = "bad gateway"
        headers = {}

    _run(out, lambda *a, **k: R(), polls=1)
    assert len(started) == 1


def test_server_unreachable_without_a_config_starts_nothing(loop_env):
    out, started, _ = loop_env

    def unreachable(*a, **k):
        raise requests.ConnectionError("connection refused")

    _run(out, unreachable, polls=1)
    assert started == []


def test_401_stops_nebula_and_deletes_config_and_key(loop_env, monkeypatch):
    out, started, stopped = loop_env
    for name in ("config.yaml", "dns-client.json", "available-routes.json"):
        (out / name).write_text("x")

    class R401:
        status_code = 401
        ok = False
        text = "unauthorized"
        headers = {}

    def unreachable_then_401(*a, **k):
        if not started:
            raise requests.ConnectionError("down")  # first: offline start from config
        return R401()

    # Let it run for a while: before the fix, the still-stored rejected token was
    # retried immediately, forever (hundreds of 401 polls per second).
    calls, statuses = _run(out, unreachable_then_401, seconds=2.5)
    assert len(started) == 1 and stopped == started  # it ran, then was stopped
    for name in ("config.yaml", "dns-client.json", "available-routes.json"):
        assert not (out / name).exists(), name
    assert any("revoked" in msg.lower() for _, msg in statuses)
    # The rejected token is still stored; the loop must wait for a NEW one rather than
    # retrying it: one failed poll (offline start), one 401, then it waits.
    assert len(calls) == 2


def test_401_in_cli_mode_exits_after_cleanup(loop_env):
    out, _, _ = loop_env
    (out / "config.yaml").write_text("x")

    class R401:
        status_code = 401
        ok = False
        text = "unauthorized"
        headers = {}

    with pytest.raises(SystemExit):
        _run(out, lambda *a, **k: R401(), polls=5, service=False)
    assert not (out / "config.yaml").exists()
