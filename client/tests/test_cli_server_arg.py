"""
`--server` works both before and after the subcommand: the docs and the
deb/rpm install message show `ncclient enroll --server URL --code X`, which
argparse used to reject because --server only existed on the top-level parser.
"""
import pytest

from client import ncclient


@pytest.fixture
def captured(monkeypatch):
    got = {}
    monkeypatch.delenv("NEBULA_COMMANDER_SERVER", raising=False)
    monkeypatch.setattr(ncclient, "_apply_linux_service_defaults", lambda cmd: None)
    monkeypatch.setattr("client.config.load_settings", lambda: {"server": "https://saved.example"})
    monkeypatch.setattr(ncclient, "cmd_enroll", lambda server, code: got.update(server=server, code=code))
    return got


@pytest.mark.parametrize("argv", [
    ["enroll", "--server", "https://nc.example", "--code", "ABC"],
    ["--server", "https://nc.example", "enroll", "--code", "ABC"],
    ["enroll", "-s", "https://nc.example", "-c", "ABC"],
])
def test_server_either_side_of_subcommand(captured, monkeypatch, argv):
    monkeypatch.setattr(ncclient.sys, "argv", ["ncclient", *argv])
    ncclient.main()
    assert captured == {"server": "https://nc.example", "code": "ABC"}


def test_omitted_server_falls_back_to_saved(captured, monkeypatch):
    monkeypatch.setattr(ncclient.sys, "argv", ["ncclient", "enroll", "--code", "ABC"])
    ncclient.main()
    assert captured["server"] == "https://saved.example"
