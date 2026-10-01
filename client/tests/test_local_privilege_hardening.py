"""
Tests for the local-privilege hardening: config.yaml private-key redaction
(service_api.redact_config_yaml, served to unprivileged callers by both the
Linux D-Bus GetConfigYaml read action and the Windows pipe's get_config_yaml),
nebula_path no longer being settable, and the Windows service-managed Nebula
installer's checksum parsing and zip-slip guard (pure logic - no network).
"""
import io
import zipfile

import pytest
import yaml

from client import service_api
from client.windows import nebula_install

KEY_PEM = (
    "-----BEGIN NEBULA X25519 PRIVATE KEY-----\n"
    "4ThE1GAsSU3VmRjHClYOxKVS/HxhO3SSb49vdmsLMi8=\n"
    "-----END NEBULA X25519 PRIVATE KEY-----\n"
)
CONFIG = (
    "pki:\n"
    "  ca: CA-PEM\n"
    "  cert: CERT-PEM\n"
    "  key: |\n"
    + "".join(f"    {line}\n" for line in KEY_PEM.splitlines())
    + "tun:\n  dev: nebula1\n"
)


def test_redact_replaces_inline_key_and_keeps_rest():
    out = service_api.redact_config_yaml(CONFIG)
    assert "PRIVATE KEY" not in out
    assert "4ThE1GAsSU3V" not in out
    parsed = yaml.safe_load(out)
    assert parsed["pki"]["key"] == service_api.REDACTED
    assert parsed["pki"]["cert"] == "CERT-PEM"
    assert parsed["tun"]["dev"] == "nebula1"


def test_redact_unparseable_yaml_still_strips_pem():
    broken = "pki: [unclosed\n" + KEY_PEM
    out = service_api.redact_config_yaml(broken)
    assert "PRIVATE KEY" not in out
    assert "4ThE1GAsSU3V" not in out


def test_get_config_yaml_is_redacted(tmp_path):
    (tmp_path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    out = service_api.get_config_yaml(str(tmp_path))
    assert "PRIVATE KEY" not in out


def test_nebula_path_not_settable(monkeypatch):
    saved = {}
    monkeypatch.setattr(service_api, "load_settings", lambda: {"server": "https://a"})
    monkeypatch.setattr(service_api, "save_settings", lambda s: saved.update(s))
    service_api.set_settings({"nebula_path": r"C:\evil.exe", "interval": 30})
    assert "nebula_path" not in saved
    assert saved["interval"] == 30


def test_parse_shasums():
    text = (
        "adbb2201c86fcce7bf68a1d4ebbeb7570b32fdb73ce9044296ea47a17ad596d7  nebula-windows-amd64.zip\n"
        "3fc950cd530966f52dded2038661c837afa8d8bc09cb590f39e8a195e2aa2274  nebula-windows-amd64.zip/nebula.exe\n"
        "garbage line\n"
    )
    sums = nebula_install._parse_shasums(text)
    assert sums["nebula-windows-amd64.zip"].startswith("adbb22")
    assert sums["nebula-windows-amd64.zip/nebula.exe"].startswith("3fc950")
    assert len(sums) == 2


def _zip_with(name: str) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, b"x")
    buf.seek(0)
    return zipfile.ZipFile(buf)


@pytest.mark.parametrize("name", ["../evil.exe", "dist/../../evil.exe", "/abs/evil.exe", "C:/evil.exe"])
def test_safe_extract_rejects_escapes(tmp_path, name):
    with pytest.raises(nebula_install.NebulaInstallError):
        nebula_install._safe_extract(_zip_with(name), str(tmp_path))


def test_safe_extract_allows_nested(tmp_path):
    nebula_install._safe_extract(_zip_with("dist/windows/wintun/bin/amd64/wintun.dll"), str(tmp_path))
    assert (tmp_path / "dist" / "windows" / "wintun" / "bin" / "amd64" / "wintun.dll").is_file()


def test_tag_validation():
    with pytest.raises(nebula_install.NebulaInstallError):
        nebula_install.prepare("v1.2.3;calc")
