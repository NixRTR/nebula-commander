"""_start_nebula passes bind_force through to exit_routing.bind_to_uplink.

Regression: with several networks, a network without its own exit route must stay bound
to the uplink while another network's exit node is active. Before the fix _start_nebula
unbound it on every start and _ensure_exit rebound it, restarting Nebula every poll."""
import sys

from client import exit_routing, ncclient


def _run(monkeypatch, tmp_path, bind_force):
    cfg = tmp_path / "config.yaml"
    cfg.write_bytes(b"listen:\n  host: 0.0.0.0\n  port: 0\n")
    seen = {}

    def fake_bind(data, force=False):
        seen["force"] = force
        return data.replace(b"0.0.0.0", b"192.0.2.10") if force else data

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(exit_routing, "bind_to_uplink", fake_bind)
    monkeypatch.setattr(ncclient, "_windows_process_is_elevated", lambda: False)  # stop before spawning
    monkeypatch.setattr(ncclient, "_which", lambda b: b)
    assert ncclient._start_nebula("nebula", str(tmp_path), bind_force=bind_force) is None
    return seen["force"], cfg.read_bytes()


def test_bind_force_keeps_uplink_binding(monkeypatch, tmp_path):
    force, data = _run(monkeypatch, tmp_path, True)
    assert force is True
    assert b"host: 192.0.2.10" in data


def test_default_does_not_force(monkeypatch, tmp_path):
    force, data = _run(monkeypatch, tmp_path, False)
    assert force is False
    assert b"host: 0.0.0.0" in data
