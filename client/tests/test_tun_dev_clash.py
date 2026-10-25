"""Two networks asking for the same tun device: servers before 0.8.0 give every network
nebula1 (or no tun.dev), so a second such network would take over the first one's
device. The supervisor renames the later one to nc-<id>, deterministically."""
import threading

import pytest
import yaml

from client import config, token_store
from client.supervisor import Supervisor

LEGACY = b"tun:\n  dev: nebula1\nlisten:\n  port: 0\n"
NO_DEV = b"listen:\n  port: 0\n"


@pytest.fixture
def sup(monkeypatch, tmp_path):
    monkeypatch.setenv("NEBULA_COMMANDER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(token_store, "_shared_dpapi_active", lambda: False)
    out = tmp_path / "out"
    out.mkdir()
    config.save_settings({"enrollments": [
        {"id": "aaaa1111", "server": "https://a"}, {"id": "bbbb2222", "server": "https://b"},
    ]})
    return Supervisor(str(out), 60, None, None, threading.Event(), log=lambda m: None)


def _write(sup, eid, data):
    d = config.enrollment_dir(sup.output_dir, eid)
    import os
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "config.yaml"), "wb").write(data)


def _dev(data):
    return (yaml.safe_load(data).get("tun") or {}).get("dev")


def test_second_legacy_network_is_renamed(sup):
    _write(sup, "aaaa1111", LEGACY)  # the first network already runs on nebula1
    assert sup._dev_filter("aaaa1111", "a")(LEGACY) == LEGACY
    assert _dev(sup._dev_filter("bbbb2222", "b")(LEGACY)) == "nc-bbbb2222"


def test_missing_tun_dev_counts_as_nebula1(sup):
    _write(sup, "aaaa1111", NO_DEV)
    assert _dev(sup._dev_filter("bbbb2222", "b")(NO_DEV)) == "nc-bbbb2222"


def test_both_fresh_the_first_in_settings_keeps_nebula1(sup):
    # neither has a config yet (enrolled at once): order decides, whoever polls first
    assert _dev(sup._dev_filter("bbbb2222", "b")(LEGACY)) == "nc-bbbb2222"
    assert sup._dev_filter("aaaa1111", "a")(LEGACY) == LEGACY


def test_a_later_network_already_on_nebula1_doesnt_take_it_from_the_first(sup):
    # e.g. both on nebula1 from an earlier version: the earlier one in settings keeps it
    _write(sup, "aaaa1111", LEGACY)
    _write(sup, "bbbb2222", LEGACY)
    assert sup._dev_filter("aaaa1111", "a")(LEGACY) == LEGACY
    assert _dev(sup._dev_filter("bbbb2222", "b")(LEGACY)) == "nc-bbbb2222"


def test_renamed_network_keeps_its_name_after_the_other_leaves(sup):
    _write(sup, "bbbb2222", b"tun:\n  dev: nc-bbbb2222\n")
    config.save_settings({"enrollments": [{"id": "bbbb2222", "server": "https://b"}]})
    assert _dev(sup._dev_filter("bbbb2222", "b")(LEGACY)) == "nc-bbbb2222"


def test_distinct_devices_are_untouched(sup):
    _write(sup, "aaaa1111", LEGACY)
    own = b"tun:\n  dev: nc-0123456789\n"
    assert sup._dev_filter("bbbb2222", "b")(own) == own


def test_same_server_assigned_name_on_two_networks(sup):
    same = b"tun:\n  dev: nc-0123456789\n"
    _write(sup, "aaaa1111", same)
    assert _dev(sup._dev_filter("bbbb2222", "b")(same)) == "nc-bbbb2222"
