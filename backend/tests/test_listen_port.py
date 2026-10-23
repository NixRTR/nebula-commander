"""
Per-node listen port: PATCH /api/nodes/{id} with listen_port through the real router,
and what the generated config's listen.port says. Nodes that never set one keep 4242
and a byte-identical config, so the upgrade doesn't change their ETag. Lighthouses
and relays can't use 0 (kernel-chosen): peers reach them at a fixed public endpoint.
"""
import pytest
import pytest_asyncio
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api import nodes as nodes_api
from backend.auth.oidc import UserInfo, require_user
from backend.database import get_session
from backend.models import Base, Network, NetworkPermission, Node, User
from backend.services.config_generator import generate_config_for_node

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
        s.add_all([
            Node(id=1, network_id=network.id, hostname="lh", ip_address="10.100.0.1", groups=[],
                 unsafe_routes=[], is_lighthouse=True, is_relay=False, public_endpoint="203.0.113.1:4242"),
            Node(id=2, network_id=network.id, hostname="laptop", ip_address="10.100.0.2", groups=[],
                 unsafe_routes=[], is_lighthouse=False, is_relay=False),
        ])
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
    app.include_router(nodes_api.router)
    app.dependency_overrides[require_user] = lambda: OWNER
    app.dependency_overrides[get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.sessions = sessions  # for tests that inspect the DB / generate configs
        yield client
    await engine.dispose()


async def _stored(api, node_id: int = 2) -> int:
    r = await api.get(f"/api/nodes/{node_id}")
    assert r.status_code == 200, r.text
    return r.json()["listen_port"]


async def _config_port(api, node_id: int = 2) -> int:
    async with api.sessions() as s:
        return yaml.safe_load(await generate_config_for_node(s, node_id))["listen"]["port"]


@pytest.mark.asyncio
async def test_unset_port_is_4242_and_the_config_is_unchanged(api):
    assert await _stored(api) == 4242
    assert await _config_port(api) == 4242

    async with api.sessions() as s:
        before = await generate_config_for_node(s, 2)
    assert (await api.patch("/api/nodes/2", json={"listen_port": 4242})).status_code == 200
    async with api.sessions() as s:
        assert await generate_config_for_node(s, 2) == before


@pytest.mark.parametrize("port", [4243, 51820, 65535, 0])
@pytest.mark.asyncio
async def test_port_round_trips_and_reaches_the_config(api, port):
    r = await api.patch("/api/nodes/2", json={"listen_port": port})
    assert r.status_code == 200, r.text
    assert await _stored(api) == port
    assert await _config_port(api) == port


@pytest.mark.asyncio
async def test_omitting_the_field_keeps_the_port(api):
    await api.patch("/api/nodes/2", json={"listen_port": 4243})
    assert (await api.patch("/api/nodes/2", json={"is_relay": False})).status_code == 200
    assert await _stored(api) == 4243


@pytest.mark.parametrize("port", [-1, 65536])
@pytest.mark.asyncio
async def test_out_of_range_is_a_400_and_leaves_the_port_unchanged(api, port):
    await api.patch("/api/nodes/2", json={"listen_port": 4243})

    r = await api.patch("/api/nodes/2", json={"listen_port": port})

    assert r.status_code == 400, r.text
    assert "0-65535" in r.json()["detail"]
    assert await _stored(api) == 4243


@pytest.mark.asyncio
async def test_lighthouse_can_move_off_4242_but_not_to_0(api):
    assert (await api.patch("/api/nodes/1", json={"listen_port": 4300})).status_code == 200
    assert await _config_port(api, 1) == 4300

    r = await api.patch("/api/nodes/1", json={"listen_port": 0})
    assert r.status_code == 400, r.text
    assert "fixed listen port" in r.json()["detail"]
    assert await _stored(api, 1) == 4300


@pytest.mark.asyncio
async def test_a_port_0_node_cannot_become_a_relay(api):
    await api.patch("/api/nodes/2", json={"listen_port": 0})

    r = await api.patch("/api/nodes/2", json={"is_relay": True})

    assert r.status_code == 400, r.text
    r = await api.get("/api/nodes/2")
    assert r.json()["is_relay"] is False
