"""
Values that reach nebula-cert arguments: group names (-groups is comma-split by
nebula-cert, so "web,admin" would sign two groups while the UI shows one) and the
network name used as the CA -name (the argument allowlist has no space).
"""
import json
import shutil
import subprocess

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.api.certificates import CreateRequest, SignRequest
from backend.api.nodes import NodeUpdate
from backend.models import Network, NetworkPermission, User
from backend.services.cert_store import host_cert_path, read_cert_store_file
from backend.tests.test_revocation import OWNER, api  # noqa: F401 - pytest fixture
from backend.utils.names import ca_name
from backend.utils.nebula_cert import cert_sign

needs_nebula_cert = pytest.mark.skipif(shutil.which("nebula-cert") is None, reason="needs nebula-cert on PATH")

BAD_GROUPS = ["web,admin", "a:b", "a/b", "has space", "-lead", "x" * 64]


@pytest.mark.parametrize("group", BAD_GROUPS)
def test_request_models_reject_unsafe_groups(group):
    with pytest.raises(ValidationError):
        CreateRequest(network_id=1, name="n", group=group)
    with pytest.raises(ValidationError):
        SignRequest(network_id=1, name="n", public_key="k", group=group)
    with pytest.raises(ValidationError):
        NodeUpdate(group=group)


@pytest.mark.parametrize("group", [None, "", "web", " db_1 ", "lab.ops-2"])
def test_request_models_accept_normal_or_no_group(group):
    expected = group.strip() if group and group.strip() else group
    assert CreateRequest(network_id=1, name="n", group=group).group == expected
    assert NodeUpdate(group=group).group == expected


def test_cert_sign_refuses_comma_inside_an_item(tmp_path):
    with pytest.raises(ValueError, match="Comma"):
        cert_sign(tmp_path / "ca.crt", tmp_path / "ca.key", name="n", ip="10.0.0.2",
                  out_crt=tmp_path / "n.crt", groups=["web,admin"])
    with pytest.raises(ValueError, match="Comma"):
        cert_sign(tmp_path / "ca.crt", tmp_path / "ca.key", name="n", ip="10.0.0.2",
                  out_crt=tmp_path / "n.crt", unsafe_subnets=["10.1.0.0/24,10.2.0.0/24"])


@pytest.mark.parametrize("name,expected", [
    ("net", "net"), ("My Network", "My-Network"), ("  Büro / Lab  ", "B-ro-Lab"), ("---", "network-7"), ("", "network-7"),
])
def test_ca_name(name, expected):
    assert ca_name(name, 7) == expected


def _print_cert(pem: str, tmp_path) -> dict:
    f = tmp_path / "print.crt"
    f.write_text(pem)
    out = subprocess.run(["nebula-cert", "print", "-json", "-path", str(f)], capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    return d[0] if isinstance(d, list) else d


@needs_nebula_cert
@pytest.mark.asyncio
async def test_api_rejects_comma_group_and_signs_normal_group(api, tmp_path):  # noqa: F811
    r = await api.post("/api/certificates/create", json={"network_id": 1, "name": "lighthouse", "is_lighthouse": True})
    assert r.status_code == 200, r.text
    r = await api.post("/api/certificates/create", json={"network_id": 1, "name": "n1", "group": "web,admin"})
    assert r.status_code == 422
    r = await api.post("/api/certificates/create", json={"network_id": 1, "name": "n1", "group": "web"})
    assert r.status_code == 200, r.text
    node_id = r.json()["node_id"]
    assert _print_cert(read_cert_store_file(host_cert_path(1, "n1")), tmp_path)["details"]["groups"] == ["web"]

    assert (await api.patch(f"/api/nodes/{node_id}", json={"group": "web,admin"})).status_code == 422
    r = await api.put("/api/networks/1/group-firewall/web,admin", json={"inbound_rules": []})
    assert r.status_code == 400


@needs_nebula_cert
@pytest.mark.asyncio
async def test_network_name_with_space_can_create_its_first_node(api, tmp_path):  # noqa: F811
    async with api.sessions() as s:
        user = await s.scalar(select(User).where(User.oidc_sub == OWNER.sub))
        network = Network(name="My Network", subnet_cidr="10.101.0.0/24")
        s.add(network)
        await s.flush()
        s.add(NetworkPermission(user_id=user.id, network_id=network.id, role="owner", can_manage_nodes=True))
        await s.commit()
        network_id = network.id

    r = await api.post("/api/certificates/create", json={"network_id": network_id, "name": "lighthouse", "is_lighthouse": True})
    assert r.status_code == 200, r.text
    async with api.sessions() as s:
        ca_path = (await s.scalar(select(Network).where(Network.id == network_id))).ca_cert_path
    from pathlib import Path
    assert _print_cert(read_cert_store_file(Path(ca_path)), tmp_path)["details"]["name"] == "My-Network"
