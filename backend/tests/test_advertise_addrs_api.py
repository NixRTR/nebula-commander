"""
PATCH /api/nodes/{id} with advertise_addrs, end to end through the real router:
validation errors come back as 400 with a user-facing detail and leave the stored
list untouched, valid lists are stored normalized and round-trip through GET, and
the generated config carries them (except on lighthouses, where nebula ignores them).

Complements test_advertise_addrs.py, which covers normalize_advertise_addrs and
build_config directly.
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


async def _stored(api, node_id: int = 2) -> list[str]:
    r = await api.get(f"/api/nodes/{node_id}")
    assert r.status_code == 200, r.text
    return r.json()["advertise_addrs"]


@pytest.mark.asyncio
async def test_valid_list_is_stored_normalized_and_round_trips(api):
    r = await api.patch("/api/nodes/2", json={"advertise_addrs": [
        "203.0.113.7:04242", " 203.0.113.7:4242 ", "[2001:db8::1]:0",
    ]})
    assert r.status_code == 200, r.text
    assert await _stored(api) == ["203.0.113.7:4242", "[2001:db8::1]:0"]


@pytest.mark.parametrize(
    "addrs, detail",
    [
        (["node.example.com:4242"], "not a hostname"),
        (["203.0.113.7:4242,198.51.100.2:4242"], "one address per entry"),
        (["240.0.0.1:4242"], "reserved"),
        (["255.255.255.255:4242"], "reserved"),
        (["10.100.0.9:4242"], "inside the Nebula network"),
        ([f"203.0.113.{i}:4242" for i in range(1, 10)], "At most 8"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_input_is_a_400_and_leaves_the_list_unchanged(api, addrs, detail):
    assert (await api.patch("/api/nodes/2", json={"advertise_addrs": ["198.51.100.2:4242"]})).status_code == 200

    r = await api.patch("/api/nodes/2", json={"advertise_addrs": addrs})

    assert r.status_code == 400, r.text
    assert detail in r.json()["detail"]
    assert await _stored(api) == ["198.51.100.2:4242"]


@pytest.mark.asyncio
async def test_empty_list_clears_and_omitting_the_field_keeps_it(api):
    await api.patch("/api/nodes/2", json={"advertise_addrs": ["198.51.100.2:4242"]})

    assert (await api.patch("/api/nodes/2", json={"is_relay": False})).status_code == 200
    assert await _stored(api) == ["198.51.100.2:4242"]

    assert (await api.patch("/api/nodes/2", json={"advertise_addrs": []})).status_code == 200
    assert await _stored(api) == []


@pytest.mark.asyncio
async def test_generated_config_carries_them_except_on_lighthouses(api):
    for node_id in (1, 2):
        r = await api.patch(f"/api/nodes/{node_id}", json={"advertise_addrs": ["198.51.100.2:4242"]})
        assert r.status_code == 200, r.text

    async with api.sessions() as s:
        node_config = yaml.safe_load(await generate_config_for_node(s, 2))
        lighthouse_config = yaml.safe_load(await generate_config_for_node(s, 1))

    assert node_config["lighthouse"]["advertise_addrs"] == ["198.51.100.2:4242"]
    assert "advertise_addrs" not in lighthouse_config["lighthouse"]
