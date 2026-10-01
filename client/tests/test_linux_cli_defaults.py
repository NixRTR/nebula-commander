"""
`sudo ncclient enroll|routes` on a host running the packaged Linux service
must act on the service's state (/var/lib/ncclient), not root's per-user
location - see client/ncclient.py's _apply_linux_service_defaults - and the
CLI's default output dir honors NEBULA_COMMANDER_OUTPUT_DIR (set by the NixOS
module's wrapper).
"""
import os

import pytest

from client import ncclient

_KEYS = ("NEBULA_COMMANDER_CONFIG_DIR", "NEBULA_DEVICE_TOKEN_FILE", "NEBULA_COMMANDER_OUTPUT_DIR")


@pytest.fixture
def linux_root(monkeypatch, tmp_path):
    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ncclient.sys, "platform", "linux")
    monkeypatch.setattr(ncclient.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(ncclient, "_LINUX_SERVICE_STATE_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("cmd", ["enroll", "routes"])
def test_root_uses_service_state(linux_root, cmd):
    ncclient._apply_linux_service_defaults(cmd)
    assert os.environ["NEBULA_COMMANDER_CONFIG_DIR"] == str(linux_root)
    assert os.environ["NEBULA_DEVICE_TOKEN_FILE"] == os.path.join(str(linux_root), "token")
    assert ncclient._default_output_dir() == str(linux_root)


def test_explicit_env_wins(linux_root, monkeypatch):
    monkeypatch.setenv("NEBULA_COMMANDER_OUTPUT_DIR", "/var/lib/ncclient/nebula")
    ncclient._apply_linux_service_defaults("routes")
    assert ncclient._default_output_dir() == "/var/lib/ncclient/nebula"


@pytest.mark.parametrize("cmd", ["run", "install"])
def test_other_commands_untouched(linux_root, cmd):
    ncclient._apply_linux_service_defaults(cmd)
    assert all(k not in os.environ for k in _KEYS)


def test_non_root_untouched(linux_root, monkeypatch):
    monkeypatch.setattr(ncclient.os, "geteuid", lambda: 1000, raising=False)
    ncclient._apply_linux_service_defaults("routes")
    assert all(k not in os.environ for k in _KEYS)


def test_no_service_untouched(linux_root, monkeypatch, tmp_path):
    monkeypatch.setattr(ncclient, "_LINUX_SERVICE_STATE_DIR", str(tmp_path / "missing"))
    ncclient._apply_linux_service_defaults("routes")
    assert all(k not in os.environ for k in _KEYS)
