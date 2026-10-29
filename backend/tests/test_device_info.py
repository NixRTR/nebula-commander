"""
GET /api/device/info: the node and network a device token belongs to. ncclient 0.8.0+
uses it to name a network it was enrolled in before the enroll reply carried the
network's name.
"""
import base64

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api import device as device_api
from backend.auth.oidc import require_device_token
from backend.database import get_session
from backend.models import Base, Network, Node


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessions() as s:
        network = Network(id=5, name="office", subnet_cidr="10.100.0.0/24")
        s.add(network)
        await s.flush()
        s.add(Node(id=2, network_id=5, hostname="laptop", ip_address="10.100.0.2", groups=[],
                   unsafe_routes=[], is_lighthouse=False, is_relay=False))
        await s.commit()

    async def _session():
        async with sessions() as s:
            yield s

    app = FastAPI()
    app.include_router(device_api.router)
    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.app = app
        yield client
    await engine.dispose()


@pytest.mark.asyncio
async def test_device_info_names_the_network(api):
    api.app.dependency_overrides[require_device_token] = lambda: 2
    r = await api.get("/api/device/info")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(base64.b64decode(body.pop("instance_key"))) == 32  # Ed25519 public key ncclient pins
    assert body == {"node_id": 2, "hostname": "laptop", "network_id": 5, "network_name": "office"}


@pytest.mark.asyncio
async def test_device_info_unknown_node_is_404(api):
    api.app.dependency_overrides[require_device_token] = lambda: 99
    assert (await api.get("/api/device/info")).status_code == 404
