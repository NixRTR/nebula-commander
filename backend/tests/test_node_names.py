"""
Node names become cert store file names (cert_store/<network>/hosts/<name>.crt|.key),
so a name must never steer that path - e.g. into another network's hosts directory.
"""
import shutil

import pytest
from pydantic import ValidationError

from backend.api.certificates import CreateRequest, SignRequest
from backend.config import settings
from backend.services.cert_store import host_cert_path, host_key_path
from backend.tests.test_revocation import api  # noqa: F401 - pytest fixture

BAD_NAMES = ["", "  ", "../../2/hosts/victim", "a/b", "a\\b", ".hidden", "..", "has space", "x" * 64, "nul\0byte"]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_request_models_reject_unsafe_names(name):
    with pytest.raises(ValidationError):
        CreateRequest(network_id=1, name=name)
    with pytest.raises(ValidationError):
        SignRequest(network_id=1, name=name, public_key="k")


@pytest.mark.parametrize("name", ["node", "web-01", "db_1", "lab.example", "x" * 63])
def test_request_models_accept_normal_names(name):
    assert CreateRequest(network_id=1, name=f" {name} ").name == name


def test_host_paths_stay_in_the_networks_hosts_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cert_store_path", str(tmp_path))
    assert host_cert_path(3, "node") == tmp_path / "3" / "hosts" / "node.crt"
    assert host_key_path(3, "node") == tmp_path / "3" / "hosts" / "node.key"
    # Looser than the request check, so existing nodes with odd-but-harmless names keep working.
    assert host_cert_path(3, "old name").name == "old name.crt"
    for bad in ["../2/hosts/victim", "a/b", "a\\b", ".", "..", ".x", ""]:
        with pytest.raises(ValueError):
            host_cert_path(3, bad)


@pytest.mark.skipif(shutil.which("nebula-cert") is None, reason="needs nebula-cert on PATH")
@pytest.mark.asyncio
async def test_create_endpoint_rejects_traversal_name(api):  # noqa: F811
    r = await api.post("/api/certificates/create", json={"network_id": 1, "name": "../../2/hosts/victim"})
    assert r.status_code == 422
    r = await api.post("/api/certificates/create", json={"network_id": 1, "name": "lighthouse", "is_lighthouse": True})
    assert r.status_code == 200, r.text
