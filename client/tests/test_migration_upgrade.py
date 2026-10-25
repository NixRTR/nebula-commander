"""Upgrading a Windows install from 0.7.2 by auto-update (seen on a real machine,
2026-10-25): the old nebula.exe was still running with nebula.log open, moving it failed
(WinError 32), the conversion aborted after copying the token and moving config.yaml into
networks/<id>, and the supervisor then deleted that directory as a "removed network" -
the device had no network until it was enrolled again."""
import os
import shutil
import threading

import pytest

from client import config, token_store
from client.supervisor import Supervisor


@pytest.fixture
def old_install(monkeypatch, tmp_path):
    monkeypatch.setenv("NEBULA_COMMANDER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("NEBULA_DEVICE_TOKEN_FILE", str(tmp_path / "state" / "token"))
    monkeypatch.setattr(token_store, "_shared_dpapi_active", lambda: False)
    out = tmp_path / "out"
    out.mkdir()
    config.save_settings({"server": "https://nc.example.com", "node_id": 2, "accept_dns": True})
    token_store.set_token("old-token")
    (out / "config.yaml").write_text("tun:\n  dev: nebula1\n")
    (out / "nebula.log").write_text("log\n")
    return out


def _locked(name):
    real = shutil.move

    def move(src, dst, *a, **k):
        if os.path.basename(src) == name:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real(src, dst, *a, **k)
    return move


def test_a_locked_log_doesnt_stop_the_conversion(old_install, monkeypatch):
    monkeypatch.setattr(shutil, "move", _locked("nebula.log"))
    assert config.migrate_to_enrollments(str(old_install))
    (e,) = config.enrollments(config.load_settings())
    assert e["server"] == "https://nc.example.com" and e["node_id"] == 2
    assert token_store.get_token(e["id"]) == "old-token"
    assert (old_install / "networks" / e["id"] / "config.yaml").exists()
    assert not config.has_unconverted_enrollment(config.load_settings())


def test_a_locked_config_is_copied(old_install, monkeypatch):
    monkeypatch.setattr(shutil, "move", _locked("config.yaml"))
    assert config.migrate_to_enrollments(str(old_install))
    (e,) = config.enrollments(config.load_settings())
    assert (old_install / "networks" / e["id"] / "config.yaml").read_text().startswith("tun:")


def test_failed_conversion_keeps_its_directory_and_is_retried(old_install, monkeypatch):
    # first attempt dies after moving config.yaml (the 0.8.0 behaviour on a locked file)
    calls = {"n": 0}
    real = config.save_settings

    def failing_save(s):
        calls["n"] += 1
        if calls["n"] == 1 and "enrollments" in s:
            raise OSError("simulated failure after moving files")
        return real(s)

    monkeypatch.setattr(config, "save_settings", failing_save)
    sup = Supervisor(str(old_install), 60, None, None, threading.Event(), log=lambda m: None)
    sup._migrate()
    (left,) = os.listdir(old_install / "networks")
    assert (old_install / "networks" / left / "config.yaml").exists()

    sup._remove_orphan_dirs()
    assert (old_install / "networks" / left).exists(), "a half-converted network's directory must survive"

    monkeypatch.setattr(sup, "_start", lambda e: None)
    sup.reconcile()  # retries the conversion
    (e,) = config.enrollments(config.load_settings())
    assert e["id"] == left, "the retry carries on in the directory the first attempt made"
    assert token_store.get_token(e["id"]) == "old-token"
    assert (old_install / "networks" / left / "config.yaml").exists()


def test_windows_stops_old_nebula_before_converting(old_install, monkeypatch):
    import sys

    from client import ncclient
    order = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ncclient, "_stop_nebula", lambda p: order.append("stop"))
    monkeypatch.setattr(config, "migrate_to_enrollments", lambda *a, **k: order.append("migrate"))
    stop = threading.Event()
    stop.set()
    Supervisor(str(old_install), 60, "nebula.exe", None, stop, log=lambda m: None).run()
    assert order[:2] == ["stop", "migrate"]


def _broken_080_state(out):
    """What 0.8.0 left behind on a machine whose conversion failed (seen on the VM):
    the old settings and token.bin still there, the token's copy under an id that no
    settings list, and that network's directory deleted."""
    (out / "config.yaml").unlink()
    token_store.set_token("old-token", "5a8dbde9")


def test_a_device_broken_by_080_recovers_on_upgrade(old_install, monkeypatch):
    _broken_080_state(old_install)
    sup = Supervisor(str(old_install), 60, None, None, threading.Event(), log=lambda m: None)
    sup._migrate()
    (e,) = config.enrollments(config.load_settings())
    assert e["server"] == "https://nc.example.com" and e["node_id"] == 2
    assert token_store.get_token(e["id"]) == "old-token"
    assert not config.has_unconverted_enrollment(config.load_settings())


def test_re_enrolled_as_the_same_node_gets_no_duplicate(old_install, monkeypatch):
    """The user's own machine: broken by 0.8.0, then enrolled again (same server and
    node) - the old settings merge into that network instead of adding a second one."""
    _broken_080_state(old_install)
    settings = config.load_settings()
    settings["enrollments"] = [{"id": "148f0d8c", "server": "https://nc.example.com", "node_id": 2, "name": "BeardedTek"}]
    config.save_settings(settings)
    token_store.set_token("new-token", "148f0d8c")
    Supervisor(str(old_install), 60, None, None, threading.Event(), log=lambda m: None)._migrate()
    (e,) = config.enrollments(config.load_settings())
    assert e["id"] == "148f0d8c"
    assert token_store.get_token("148f0d8c") == "new-token", "the new enrollment's token wins"
    assert token_store.get_token() is None, "the old token is cleaned up"
