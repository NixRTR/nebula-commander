"""
Revocation that Nebula enforces (services/revocation.py), end to end through the real
HTTP endpoints with real nebula-cert certificates:

- revoke / delete / re-enroll put the node's certificate fingerprint into every
  remaining node's pki.blocklist (with disconnect_invalid), and invalidate the device
  token (the device gets 401);
- a re-sign after a group change blocklists the superseded certificate, so the removed
  group's firewall access really goes away;
- the released overlay IP is quarantined until the old certificate expires: never
  reissued to another node, but reclaimable by the same node (re-enroll keeps its IP);
- blocklist entries are pruned once the certificate has expired.
"""
import shutil
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api import certificates as certificates_api
from backend.api import device as device_api
from backend.api import nodes as nodes_api
from backend.auth.oidc import UserInfo, create_device_token, require_user
from backend.config import settings
from backend.database import get_session
from backend.models import AllocatedIP, Base, BlockedCertificate, Network, NetworkPermission, Node, User
from backend.services.revocation import active_blocklist, host_cert_path
from backend.utils.nebula_cert import cert_info
from backend.services.cert_store import read_cert_store_file

pytestmark = pytest.mark.skipif(shutil.which("nebula-cert") is None, reason="needs nebula-cert on PATH")

OWNER = UserInfo(sub="owner-sub", email="owner@example.com", system_role="user")


@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cert_store_path", str(tmp_path / "certs"))

    async def _no_reauth(*_args, **_kwargs):
        return None

    monkeypatch.setattr(nodes_api, "_verify_reauth_or_403", _no_reauth)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessions() as s:
        user = User(oidc_sub=OWNER.sub, email=OWNER.email, system_role="user")
        network = Network(name="net", subnet_cidr="10.100.0.0/24")
        s.add_all([user, network])
        await s.flush()
        s.add(NetworkPermission(user_id=user.id, network_id=network.id, role="owner", can_manage_nodes=True))
        await s.commit()

    async def _session():
        async with sessions() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app = FastAPI()
    for router in (certificates_api.router, nodes_api.router, device_api.router):
        app.include_router(router)
    app.dependency_overrides[require_user] = lambda: OWNER
    app.dependency_overrides[get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.sessions = sessions
        yield client
    await engine.dispose()


async def _create(api, name: str, **extra) -> int:
    body = {"network_id": 1, "name": name, **extra}
    r = await api.post("/api/certificates/create", json=body)
    assert r.status_code == 200, r.text
    return r.json()["node_id"]


async def _setup(api) -> tuple[int, int, int]:
    lighthouse = await _create(api, "lighthouse", is_lighthouse=True, public_endpoint="203.0.113.1:4242")
    a = await _create(api, "node-a")
    b = await _create(api, "node-b")
    return lighthouse, a, b


async def _node(api, node_id: int) -> Node:
    async with api.sessions() as s:
        return await s.scalar(select(Node).where(Node.id == node_id))


def _fingerprint(network_id: int, hostname: str) -> str:
    return cert_info(read_cert_store_file(host_cert_path(network_id, hostname)))[0]


async def _device_config(api, node: Node) -> "tuple[int, dict | None]":
    token = create_device_token(node.id, node.device_token_version or 1)
    r = await api.get("/api/device/config", headers={"Authorization": f"Bearer {token}"})
    return r.status_code, (yaml.safe_load(r.text) if r.status_code == 200 else None)


@pytest.mark.asyncio
async def test_configs_have_disconnect_invalid_and_no_blocklist_initially(api):
    _, a, _ = await _setup(api)
    status, config = await _device_config(api, await _node(api, a))
    assert status == 200
    assert config["pki"]["disconnect_invalid"] is True
    assert "blocklist" not in config["pki"]


@pytest.mark.asyncio
async def test_revoke_blocklists_cert_everywhere_and_kills_token(api):
    _, a, b = await _setup(api)
    node_a = await _node(api, a)
    fp_a = _fingerprint(1, "node-a")

    r = await api.post(f"/api/nodes/{a}/revoke-certificate", json={"reauth_token": "x", "confirmation": "node-a"})
    assert r.status_code == 200, r.text

    status, config_b = await _device_config(api, await _node(api, b))
    assert status == 200
    assert fp_a in config_b["pki"]["blocklist"]
    assert config_b["pki"]["disconnect_invalid"] is True

    # The old device token no longer works: an unmodified client gets 401 and shuts down.
    old_status, _ = await _device_config(api, node_a)
    assert old_status == 401


@pytest.mark.asyncio
async def test_delete_blocklists_and_quarantines_ip_for_nobody(api):
    _, a, b = await _setup(api)
    ip_a = (await _node(api, a)).ip_address
    fp_a = _fingerprint(1, "node-a")

    r = await api.request("DELETE", f"/api/nodes/{a}", json={"reauth_token": "x", "confirmation": "node-a"})
    assert r.status_code == 204, r.text

    _, config_b = await _device_config(api, await _node(api, b))
    assert fp_a in config_b["pki"]["blocklist"]

    async with api.sessions() as s:
        row = await s.scalar(select(AllocatedIP).where(AllocatedIP.ip_address == ip_a))
    assert row is not None and row.quarantined_until is not None and row.node_id is None

    # A new node must not get the deleted node's address - neither on request...
    r = await api.post("/api/certificates/create", json={"network_id": 1, "name": "node-c", "suggested_ip": ip_a})
    assert r.status_code == 409 and "revoked or deleted" in r.json()["detail"]
    # ...nor by automatic allocation.
    c = await _create(api, "node-c")
    assert (await _node(api, c)).ip_address != ip_a


@pytest.mark.asyncio
async def test_reenroll_blocklists_old_cert_and_keeps_the_ip(api):
    _, a, b = await _setup(api)
    before = await _node(api, a)
    fp_old = _fingerprint(1, "node-a")

    r = await api.post(f"/api/nodes/{a}/re-enroll")
    assert r.status_code == 200, r.text

    after = await _node(api, a)
    assert after.ip_address == before.ip_address  # reclaimed its own quarantined address
    assert _fingerprint(1, "node-a") != fp_old
    _, config_b = await _device_config(api, await _node(api, b))
    assert fp_old in config_b["pki"]["blocklist"]
    old_status, _ = await _device_config(api, before)
    assert old_status == 401


@pytest.mark.asyncio
async def test_group_change_resign_blocklists_the_superseded_cert(api):
    _, a, b = await _setup(api)
    assert (await api.patch(f"/api/nodes/{a}", json={"group": "admins"})).status_code == 200
    fp_with_admins = _fingerprint(1, "node-a")

    # Removing the group re-signs the cert; the old one (still carrying "admins") must
    # be rejected by peers, or the group's firewall access would survive the removal.
    assert (await api.patch(f"/api/nodes/{a}", json={"group": ""})).status_code == 200
    assert _fingerprint(1, "node-a") != fp_with_admins

    _, config_b = await _device_config(api, await _node(api, b))
    assert fp_with_admins in config_b["pki"]["blocklist"]
    # The node itself keeps working with its new cert (same token, not revoked).
    status, config_a = await _device_config(api, await _node(api, a))
    assert status == 200 and _fingerprint(1, "node-a") not in config_a["pki"].get("blocklist", [])


@pytest.mark.asyncio
async def test_expired_blocklist_entries_are_pruned(api):
    _, a, _ = await _setup(api)
    await api.post(f"/api/nodes/{a}/revoke-certificate", json={"reauth_token": "x", "confirmation": "node-a"})
    async with api.sessions() as s:
        assert len(await active_blocklist(s, 1)) == 1
        await s.execute(update(BlockedCertificate).values(expires_at=datetime.utcnow() - timedelta(minutes=1)))
        assert await active_blocklist(s, 1) == []
        await s.commit()
        assert (await s.scalar(select(BlockedCertificate))) is None


@pytest.mark.asyncio
async def test_quarantine_expires_and_frees_the_address(api):
    _, a, _ = await _setup(api)
    ip_a = (await _node(api, a)).ip_address
    await api.request("DELETE", f"/api/nodes/{a}", json={"reauth_token": "x", "confirmation": "node-a"})
    async with api.sessions() as s:
        await s.execute(
            update(AllocatedIP).where(AllocatedIP.ip_address == ip_a)
            .values(quarantined_until=datetime.utcnow() - timedelta(minutes=1))
        )
        await s.commit()
    c = await _create(api, "node-c", suggested_ip=ip_a)
    assert (await _node(api, c)).ip_address == ip_a
