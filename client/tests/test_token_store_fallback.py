"""
A pip-installed ncclient on a headless server can have a keyring backend that
exists but can't be used (Secret Service collection locked, no D-Bus session).
Enrolling must still store the token - in ~/.nebula/device-token - and later
reads must find it; a later successful keyring write must not be shadowed by
that file.
"""
import os
import stat
import sys
import types

import pytest

from client import token_store


class _LockedKeyring(types.ModuleType):
    def __init__(self):
        super().__init__("keyring")

    def set_password(self, *a):
        raise RuntimeError("Failed to unlock the collection!")

    def get_password(self, *a):
        raise RuntimeError("Failed to unlock the collection!")


class _WorkingKeyring(types.ModuleType):
    def __init__(self):
        super().__init__("keyring")
        self.store = {}

    def set_password(self, service, key, value):
        self.store[(service, key)] = value

    def get_password(self, service, key):
        return self.store.get((service, key))


@pytest.fixture
def home(monkeypatch, tmp_path):
    for k in ("NEBULA_DEVICE_TOKEN_FILE", "NEBULA_COMMANDER_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(token_store, "_default_token_path", lambda: str(tmp_path / ".nebula" / "device-token"))
    return tmp_path


def test_locked_keyring_falls_back_to_file(home, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "keyring", _LockedKeyring())
    token_store.set_token("tok-1")
    path = home / ".nebula" / "device-token"
    assert path.read_text(encoding="utf-8") == "tok-1"
    assert "Keyring unavailable" in capsys.readouterr().err
    assert token_store.get_token() == "tok-1"
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_keyring_write_removes_stale_fallback(home, monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", _LockedKeyring())
    token_store.set_token("old")
    kr = _WorkingKeyring()
    monkeypatch.setitem(sys.modules, "keyring", kr)
    token_store.set_token("new")
    assert not (home / ".nebula" / "device-token").exists()
    assert token_store.get_token() == "new"
