"""systemctl runs with the system's environment, not the frozen binary's bundled-library
one (Debian 13: 'OPENSSL_3.4.0 not found' from systemctl under PyInstaller)."""
import subprocess

from client.linux import auto_update


def test_systemctl_strips_bundled_library_path(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123")
    seen = {}

    class R:
        returncode, stdout, stderr = 0, "", ""

    def run(argv, **kw):
        seen["env"] = kw.get("env")
        return R()

    monkeypatch.setattr(subprocess, "run", run)
    auto_update._systemctl("daemon-reload")
    assert seen["env"] is not None
    assert seen["env"].get("LD_LIBRARY_PATH") != "/tmp/_MEI123"
