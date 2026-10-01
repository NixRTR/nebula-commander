"""Auto-update: deb/rpm timer + upgrade, service_api, the Windows updater's steps."""
import hashlib
import json
import subprocess

import pytest

from client import service_api, updates
from client.linux import auto_update
from client.updates import UpdateError


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("NEBULA_COMMANDER_CONFIG_DIR", str(tmp_path))
    return tmp_path


# --- Linux: repo detection, timer drop-in, upgrade commands ---------------------------

def test_repo_detection(tmp_path):
    ours = tmp_path / "nebula-commander.sources"
    ours.write_text("Types: deb\nURIs: https://pkgs.nebulacommander.com/deb\n")
    other = tmp_path / "other.repo"
    other.write_text("baseurl=https://example.com/rpm\n")
    assert auto_update.repo_configured((str(tmp_path / "missing"), str(ours)))
    assert not auto_update.repo_configured((str(other),))


def test_timer_dropin_covers_window():
    d = auto_update.timer_dropin("02:00", "05:00")
    assert "OnCalendar=\nOnCalendar=*-*-* 02:00:00" in d  # resets the unit's default first
    assert "RandomizedDelaySec=10800" in d
    assert "Persistent=false" in d
    assert "RandomizedDelaySec=7200" in auto_update.timer_dropin("23:00", "01:00")  # wraps midnight


def test_enable_refused_without_repo(monkeypatch):
    monkeypatch.setattr(auto_update, "repo_configured", lambda *a: False)
    calls = []
    monkeypatch.setattr(auto_update, "_systemctl", lambda *a: calls.append(a))
    with pytest.raises(UpdateError, match="package repository"):
        auto_update.apply(True, "02:00", "05:00")
    assert calls == []
    auto_update.apply(False, "02:00", "05:00")  # turning off always works
    assert calls == [("disable", "--now", auto_update.TIMER)]


def test_enable_writes_dropin_and_arms_timer(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_update, "repo_configured", lambda *a: True)
    monkeypatch.setattr(auto_update, "DROPIN_DIR", str(tmp_path / "d"))
    monkeypatch.setattr(auto_update, "DROPIN", str(tmp_path / "d" / "window.conf"))
    calls = []
    monkeypatch.setattr(auto_update, "_systemctl", lambda *a: calls.append(a))
    auto_update.apply(True, "01:30", "04:00")
    assert "OnCalendar=*-*-* 01:30:00" in (tmp_path / "d" / "window.conf").read_text()
    assert ("daemon-reload",) in calls and ("enable", "--now", auto_update.TIMER) in calls


def test_upgrade_commands_only_touch_our_packages():
    pkgs = ["nebula-commander-client", "nebula-commander-service"]
    apt = auto_update.upgrade_commands("apt-get", pkgs, "/etc/apt/sources.list.d/nebula-commander.sources")
    assert apt[0][:2] == ["apt-get", "update"]
    assert "Dir::Etc::sourcelist=/etc/apt/sources.list.d/nebula-commander.sources" in apt[0]
    assert apt[1][:3] == ["apt-get", "install", "--only-upgrade"] and apt[1][-2:] == pkgs
    assert auto_update.upgrade_commands("dnf", pkgs) == [["dnf", "-y", "--refresh", "upgrade", *pkgs]]
    zyp = auto_update.upgrade_commands("zypper", pkgs)
    assert zyp[0] == ["zypper", "--non-interactive", "refresh", "nebula-commander"]
    for cmds in (apt, zyp):
        assert not any("--gpg-auto-import-keys" in c or "--allow-unauthenticated" in c for argv in cmds for c in argv)


def test_run_upgrade_records_changes(state, monkeypatch):
    monkeypatch.setattr(auto_update, "repo_configured", lambda *a: True)
    monkeypatch.setattr(auto_update, "_package_manager", lambda: "dnf")
    versions = iter([{"nebula-commander-client": "0.7.0"}, {"nebula-commander-client": "0.7.1"}])
    monkeypatch.setattr(auto_update, "installed_packages", lambda pm: next(versions))
    ran = []
    monkeypatch.setattr(auto_update, "_run", lambda argv, log: ran.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    st = auto_update.run_upgrade(log=lambda m: None)
    assert ran == [["dnf", "-y", "--refresh", "upgrade", "nebula-commander-client"]]
    assert st["last_install_result"] == "updated"
    assert st["last_install_changes"] == {"nebula-commander-client": "0.7.0 -> 0.7.1"}


def test_run_upgrade_records_failure(state, monkeypatch):
    monkeypatch.setattr(auto_update, "repo_configured", lambda *a: True)
    monkeypatch.setattr(auto_update, "_package_manager", lambda: "dnf")
    monkeypatch.setattr(auto_update, "installed_packages", lambda pm: {"nebula-commander-client": "0.7.0"})
    monkeypatch.setattr(auto_update, "_run", lambda argv, log: subprocess.CompletedProcess(argv, 1, "", "Error: GPG check FAILED"))
    st = auto_update.run_upgrade(log=lambda m: None)
    assert st["last_install_result"] == "error" and "GPG check FAILED" in st["last_install_error"]
    assert json.loads((state / "update-status.json").read_text())["last_install_result"] == "error"


# --- service_api ---------------------------------------------------------------------

def test_set_auto_update_refused_on_unsupported_install(state, monkeypatch):
    monkeypatch.setattr(updates, "install_kind", lambda: "unsupported")
    with pytest.raises(service_api.UpdateSettingsError, match="aren't available"):
        service_api.set_auto_update(True)
    service_api.set_auto_update(False)  # turning it off is always allowed


def test_set_auto_update_validates_and_saves(state, monkeypatch):
    monkeypatch.setattr(updates, "install_kind", lambda: "nixos")
    with pytest.raises(service_api.UpdateSettingsError, match="HH:MM"):
        service_api.set_auto_update(True, "25:00", "03:00")
    st = service_api.set_auto_update(True, "01:00", "03:00")
    assert st["mode"] == "notify" and st["enabled"] and st["window_start"] == "01:00"
    saved = json.loads((state / "settings.json").read_text())["auto_update"]
    assert saved == {"enabled": True, "window_start": "01:00", "window_end": "03:00"}
    # partial update keeps the window
    assert service_api.set_auto_update(False)["window_start"] == "01:00"


def test_set_auto_update_package_arms_timer_or_refuses(state, monkeypatch):
    monkeypatch.setattr(updates, "install_kind", lambda: "package")
    applied = []

    def fake_apply(enabled, start, end):
        if enabled and not applied_ok:
            raise UpdateError("Automatic updates need the official Nebula Commander package repository")
        applied.append((enabled, start, end))

    monkeypatch.setattr(auto_update, "apply", fake_apply)
    applied_ok = False
    with pytest.raises(service_api.UpdateSettingsError, match="package repository"):
        service_api.set_auto_update(True)
    assert not (state / "settings.json").exists()  # nothing saved when refused
    applied_ok = True
    service_api.set_auto_update(True, "02:00", "04:00")
    assert applied == [(True, "02:00", "04:00")]


def test_check_now_starts_package_upgrade_only_when_on(state, monkeypatch):
    monkeypatch.setattr(updates, "install_kind", lambda: "package")
    monkeypatch.setattr(updates, "check", lambda kind=None: {"available_version": "0.7.1", "manifest": {}})
    started = []
    monkeypatch.setattr(auto_update, "run_now", lambda: started.append(1))
    st = service_api.check_updates_now()
    assert started == [] and "manifest" not in st  # off: check only
    monkeypatch.setattr(auto_update, "apply", lambda *a: None)
    service_api.set_auto_update(True)
    assert service_api.check_updates_now()["install_started"] and started == [1]


# --- heartbeat -----------------------------------------------------------------------

def test_heartbeat_fields(state, monkeypatch):
    from client import ncclient

    monkeypatch.setattr(updates, "install_kind", lambda: "nixos")
    updates.save_status({"available_version": "0.7.1"})
    f = ncclient._update_heartbeat_fields()
    assert f["auto_update"] == "off" and f["update_available"] == "0.7.1" and f["client_version"]


# --- Windows updater steps (platform-independent parts) -------------------------------

class _Resp:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self._data


def test_download_verified_discards_mismatch(tmp_path, monkeypatch):
    import requests

    from client.windows import updater

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(b"evil"))
    dest = tmp_path / "x.msi"
    with pytest.raises(UpdateError, match="doesn't match"):
        updater.download_verified("https://x", hashlib.sha256(b"good").hexdigest(), str(dest))
    assert not dest.exists() and not (tmp_path / "x.msi.part").exists()
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(b"good"))
    updater.download_verified("https://x", hashlib.sha256(b"good").hexdigest(), str(dest))
    assert dest.read_bytes() == b"good"


def test_msiexec_is_quiet_and_logged():
    from client.windows import updater

    argv = updater.msiexec_argv(r"C:\x\a.msi", r"C:\x\a.log")
    assert argv[0].lower().endswith(r"system32\msiexec.exe")
    assert argv[1:] == ["/i", r"C:\x\a.msi", "/qn", "/norestart", "/l*v", r"C:\x\a.log"]


@pytest.mark.parametrize("running,result", [("0.7.1", "updated"), ("0.7.0", "error")])
def test_record_pending_result(state, monkeypatch, running, result):
    from client.windows import updater

    monkeypatch.setattr(updater, "VERSION", running)
    (state / "updates").mkdir()
    (state / "updates" / "pending-update.json").write_text(json.dumps(
        {"version": "0.7.1", "from_version": "0.7.0", "msi": str(state / "updates" / "a.msi"),
         "log": "C:/log.txt", "started": "2026-10-01T02:00:00Z"}))
    updater.record_pending_result(lambda m: None)
    st = updates.load_status()
    assert st["last_install_result"] == result
    assert not (state / "updates" / "pending-update.json").exists()


def test_dev_build_never_installs(state, monkeypatch):
    import threading

    from client.windows import updater

    manifest = {"version": "9.9.9", "assets": {}}
    monkeypatch.setattr(updates, "check", lambda kind=None: {"available_version": "9.9.9", "manifest": manifest})
    monkeypatch.setattr(updater, "is_dev_build", lambda: True)
    monkeypatch.setattr(updater, "start_install", lambda *a: pytest.fail("installed a dev build"))
    updater.Updater(threading.Event(), lambda m: None).run_once(install=True)
