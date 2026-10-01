"""client/updates.py: manifest trust, version compare, the window, NixOS notify."""
import base64
import datetime as dt
import json
import random

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from client import updates
from client.updates import UpdateError

SHA = "a" * 64
URL = "https://github.com/NixRTR/nebula-commander/releases/download/v0.7.1/NebulaCommander-0.7.1.msi"


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv, pub


def _manifest(**over):
    m = {"schema": 1, "version": "0.7.1", "tag": "v0.7.1", "git_commit": "c" * 40,
         "commit_time": 2_000_000_000, "released": "2026-10-01T00:00:00Z",
         "assets": {"windows-amd64": {"url": URL, "sha256": SHA}}}
    m.update(over)
    return json.dumps(m).encode()


def _sign(priv, body):
    return base64.b64encode(priv.sign(body))


# --- manifest ------------------------------------------------------------------------

def test_valid_manifest_verifies():
    priv, pub = _keypair()
    body = _manifest()
    assert updates.verify_manifest(body, _sign(priv, body), [pub])["version"] == "0.7.1"


def test_any_listed_key_is_accepted():
    priv, pub = _keypair()
    _, other = _keypair()
    body = _manifest()
    assert updates.verify_manifest(body, _sign(priv, body), [other, pub])


def test_tampered_body_rejected():
    priv, pub = _keypair()
    body = _manifest()
    sig = _sign(priv, body)
    with pytest.raises(UpdateError, match="signature is not valid"):
        updates.verify_manifest(body.replace(b"0.7.1", b"0.7.9"), sig, [pub])


def test_wrong_key_rejected():
    priv, _ = _keypair()
    _, pub = _keypair()
    body = _manifest()
    with pytest.raises(UpdateError, match="signature is not valid"):
        updates.verify_manifest(body, _sign(priv, body), [pub])


def test_no_trusted_keys_rejects_everything():
    priv, _ = _keypair()
    body = _manifest()
    with pytest.raises(UpdateError):
        updates.verify_manifest(body, _sign(priv, body), [])


def test_garbage_signature_rejected():
    _, pub = _keypair()
    with pytest.raises(UpdateError, match="malformed"):
        updates.verify_manifest(_manifest(), b"not base64!!", [pub])


@pytest.mark.parametrize("url", [
    "https://evil.example.com/NebulaCommander.msi",
    "http://github.com/NixRTR/nebula-commander/releases/download/v0.7.1/x.msi",
    "https://github.com/NixRTR/nebula-commander-evil/releases/download/v0.7.1/x.msi",
    "https://github.com/NixRTR/nebula-commander/releases/download/../../other/x.msi",
])
def test_signed_manifest_with_foreign_asset_url_rejected(url):
    priv, pub = _keypair()
    body = _manifest(assets={"windows-amd64": {"url": url, "sha256": SHA}})
    with pytest.raises(UpdateError, match="outside the official releases"):
        updates.verify_manifest(body, _sign(priv, body), [pub])


@pytest.mark.parametrize("over,match", [
    ({"schema": 2}, "unknown format"),
    ({"version": "0.8.0-rc1"}, "no stable version"),
    ({"assets": {"windows-amd64": {"url": URL, "sha256": "xyz"}}}, "SHA-256"),
])
def test_signed_but_malformed_manifest_rejected(over, match):
    priv, pub = _keypair()
    body = _manifest(**over)
    with pytest.raises(UpdateError, match=match):
        updates.verify_manifest(body, _sign(priv, body), [pub])


# --- versions ------------------------------------------------------------------------

@pytest.mark.parametrize("candidate,current,expected", [
    ("0.7.1", "0.7.0", True),
    ("0.10.0", "0.9.9", True),
    ("v1.0.0", "0.99.99", True),
    ("0.7.0", "0.7.0", False),
    ("0.6.9", "0.7.0", False),          # never downgrade
    ("0.7.1", "0.0.0+dev", False),      # dev builds are never replaced
    ("0.8.0-rc1", "0.7.0", False),      # no pre-releases
    ("0.7.1", "0.7.1-rc1", False),
])
def test_is_newer(candidate, current, expected):
    assert updates.is_newer(candidate, current) is expected


@pytest.mark.parametrize("version,dev", [
    ("0.0.0+dev", True), ("0.0.0+git.f67bc81", True), ("0.7.0", False), ("0.7.1-rc1", False),
])
def test_is_dev_build(version, dev):
    from client.version import is_dev_build

    assert is_dev_build(version) is dev


def test_evaluate_nix_build_reports_by_commit():
    m = json.loads(_manifest())
    assert updates.evaluate(m, "nixos", current="0.0.0+git.ddddddd", git_commit="d" * 40,
                            source_date=1_900_000_000) == "0.7.1"


def test_evaluate_release_build():
    m = json.loads(_manifest())
    assert updates.evaluate(m, "windows", current="0.7.0") == "0.7.1"
    assert updates.evaluate(m, "windows", current="0.7.1") is None


def test_evaluate_dev_build_never_updates():
    m = json.loads(_manifest())
    assert updates.evaluate(m, "windows", current="0.0.0+dev", git_commit=None, source_date=None) is None
    assert updates.evaluate(m, "package", current="0.0.0+dev", git_commit="d" * 40, source_date=1) is None


def test_evaluate_nixos_by_commit():
    m = json.loads(_manifest())
    dev = "0.0.0+dev"
    # built from the released commit: up to date
    assert updates.evaluate(m, "nixos", current=dev, git_commit="c" * 40, source_date=2_000_000_000) is None
    # built from an older commit: update available
    assert updates.evaluate(m, "nixos", current=dev, git_commit="d" * 40, source_date=1_900_000_000) == "0.7.1"
    # built from a newer commit (e.g. main after the release): nothing to do
    assert updates.evaluate(m, "nixos", current=dev, git_commit="d" * 40, source_date=2_100_000_000) is None
    # unknown commit: can't tell, so stay quiet
    assert updates.evaluate(m, "nixos", current=dev, git_commit=None, source_date=None) is None


def test_nixos_instructions_name_the_tag():
    cmds = updates.nixos_update_commands({"tag": "v0.7.1"})
    assert "sudo nixos-rebuild switch" in cmds
    assert any("github:NixRTR/nebula-commander/v0.7.1" in c for c in cmds)


# --- settings / mode -----------------------------------------------------------------

@pytest.mark.parametrize("start,end", [("2:00", "05:00"), ("24:00", "05:00"), ("02:00", "02:00"), ("", "05:00")])
def test_validate_settings_rejects_bad_windows(start, end):
    with pytest.raises(UpdateError):
        updates.validate_settings(True, start, end)


def test_settings_default_off_and_tolerate_garbage():
    assert updates.auto_update_settings({}) == updates.DEFAULT_SETTINGS
    s = updates.auto_update_settings({"auto_update": {"enabled": True, "window_start": "nope"}})
    assert s["enabled"] is True and s["window_start"] == "02:00"


@pytest.mark.parametrize("kind,enabled,expected", [
    ("windows", True, "install"), ("package", True, "install"), ("nixos", True, "notify"),
    ("windows", False, "off"), ("unsupported", True, "off"),
])
def test_mode(kind, enabled, expected):
    assert updates.mode({"auto_update": {"enabled": enabled}}, kind) == expected


def test_install_kind_from_env(monkeypatch):
    monkeypatch.setenv("NEBULA_COMMANDER_INSTALL_KIND", "nixos")
    assert updates.install_kind() == "nixos"
    monkeypatch.setenv("NEBULA_COMMANDER_INSTALL_KIND", "something-else")
    monkeypatch.setattr(updates.sys, "frozen", False, raising=False)
    assert updates.install_kind() == "unsupported"


# --- window --------------------------------------------------------------------------

def _at(h, m=0, day=1):
    return dt.datetime(2026, 10, day, h, m)


def _runs(now, start, end, n=200):
    rng = random.Random(1)
    return [updates.next_run(now, start, end, rng) for _ in range(n)]


def test_before_window_runs_inside_todays_window():
    for r in _runs(_at(1), "02:00", "05:00"):
        assert _at(2) <= r < _at(5)


def test_inside_window_runs_between_now_and_end():
    for r in _runs(_at(3, 30), "02:00", "05:00"):
        assert _at(3, 30) <= r < _at(5)


def test_after_window_runs_tomorrow():
    for r in _runs(_at(6), "02:00", "05:00"):
        assert _at(2, day=2) <= r < _at(5, day=2)


def test_window_wrapping_midnight():
    # 23:00-01:00: at 00:30 we're still inside yesterday's window
    for r in _runs(_at(0, 30), "23:00", "01:00"):
        assert _at(0, 30) <= r < _at(1)
    # at 12:00 the next window starts tonight
    for r in _runs(_at(12), "23:00", "01:00"):
        assert _at(23) <= r < _at(1, day=2)


def test_window_end_after_moves_past_current_window():
    assert updates.window_end_after(_at(3), "02:00", "05:00") == _at(5)
    assert updates.window_end_after(_at(0, 30), "23:00", "01:00") == _at(1)
    # one run per window: the next slot after this window's end is tomorrow
    nxt = updates.next_run(updates.window_end_after(_at(3), "02:00", "05:00"), "02:00", "05:00")
    assert nxt >= _at(2, day=2)


# --- check() / status file -----------------------------------------------------------

def test_check_records_status_and_never_persists_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("NEBULA_COMMANDER_CONFIG_DIR", str(tmp_path))
    m = json.loads(_manifest())
    monkeypatch.setattr(updates, "fetch_manifest", lambda url=None: m)
    monkeypatch.setattr(updates._version, "VERSION", "0.7.0")
    st = updates.check("windows")
    assert st["available_version"] == "0.7.1" and st["manifest"] == m
    saved = json.loads((tmp_path / "update-status.json").read_text())
    assert saved["last_result"] == "update_available" and "manifest" not in saved


def test_check_records_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("NEBULA_COMMANDER_CONFIG_DIR", str(tmp_path))

    def boom(url=None):
        raise UpdateError("Update manifest signature is not valid - refusing to use it")

    monkeypatch.setattr(updates, "fetch_manifest", boom)
    st = updates.check("windows")
    assert st["last_result"] == "error" and "not valid" in st["last_error"]
    assert "manifest" not in st
