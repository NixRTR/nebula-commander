"""
Heartbeat: client version / auto-update state are stored as reported (sanitized),
shown read-only on the node, and left alone by clients that don't send them.
"""
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api import heartbeat as heartbeat_api
from backend.api import nodes as nodes_api
from backend.auth.oidc import UserInfo, require_device_token, require_user
from backend.database import get_session
from backend.models import Base, Network, NetworkPermission, Node, User

OWNER = UserInfo(sub="owner-sub", email="owner@example.com", system_role="user")


@pytest_asyncio.fixture
async def api(tmp_path):
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
        s.add(Node(id=2, network_id=network.id, hostname="laptop", ip_address="10.100.0.2", groups=[],
                   unsafe_routes=[], is_lighthouse=False, is_relay=False))
        await s.commit()

    async def _session():
        async with sessions() as s:
            yield s
            await s.commit()

    app = FastAPI()
    app.include_router(nodes_api.router)
    app.include_router(heartbeat_api.router)
    app.dependency_overrides[require_user] = lambda: OWNER
    app.dependency_overrides[require_device_token] = lambda: 2
    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await engine.dispose()


async def _node(api):
    r = await api.get("/api/nodes/2")
    assert r.status_code == 200, r.text
    j = r.json()
    return j["client_version"], j["auto_update"], j["update_available"]


@pytest.mark.asyncio
async def test_reported_and_shown(api):
    r = await api.post("/api/nodes/2/heartbeat", json={
        "client_version": "0.7.0", "auto_update": "notify", "update_available": "0.7.1"})
    assert r.status_code == 200, r.text
    assert await _node(api) == ("0.7.0", "notify", "0.7.1")
    # update installed: null clears it
    await api.post("/api/nodes/2/heartbeat", json={
        "client_version": "0.7.1", "auto_update": "notify", "update_available": None})
    assert await _node(api) == ("0.7.1", "notify", None)


@pytest.mark.asyncio
async def test_older_clients_leave_fields_alone(api):
    await api.post("/api/nodes/2/heartbeat", json={"client_version": "0.7.0", "auto_update": "install"})
    await api.post("/api/nodes/2/heartbeat", json={"interval_seconds": 60})
    assert await _node(api) == ("0.7.0", "install", None)


@pytest.mark.asyncio
async def test_garbage_is_dropped(api):
    await api.post("/api/nodes/2/heartbeat", json={
        "client_version": "<script>alert(1)</script>", "auto_update": "yes-please",
        "update_available": "9" * 40})
    assert await _node(api) == (None, None, None)
