"""`ncclient run` with nothing enrolled starts and waits instead of exiting.

Found testing a fresh 0.8.0 install: the service exited (systemd retried every 30 s),
so the desktop app's Add network - a D-Bus call into that service - had nothing to
talk to."""
import sys

import pytest

from client import ncclient


def test_run_without_enrollments_starts(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("NEBULA_COMMANDER_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("NEBULA_COMMANDER_SERVER", raising=False)
    monkeypatch.setattr(ncclient, "_apply_linux_service_defaults", lambda cmd: None)
    started = {}
    monkeypatch.setattr(ncclient, "cmd_run", lambda server, *a, **k: started.setdefault("server", server))
    monkeypatch.setattr(sys, "argv", ["ncclient", "run", "--output-dir", str(tmp_path / "out")])
    ncclient.main()
    assert "server" in started and started["server"] is None
    assert "waiting for one" in capsys.readouterr().err


def test_enroll_still_needs_a_server(monkeypatch, tmp_path):
    monkeypatch.setenv("NEBULA_COMMANDER_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("NEBULA_COMMANDER_SERVER", raising=False)
    monkeypatch.setattr(ncclient, "_apply_linux_service_defaults", lambda cmd: None)
    monkeypatch.setattr(sys, "argv", ["ncclient", "enroll", "--code", "X"])
    with pytest.raises(SystemExit):
        ncclient.main()
