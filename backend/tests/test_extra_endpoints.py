"""
Additional endpoints per node: more static_host_map addresses after the public endpoint,
so e.g. an office lighthouse can be reached by its LAN address from inside the office
and by the office's public address from everywhere else. Nebula tries every address it
is given for a host. Checked through the real nodes router and the generated config.
"""
import sqlite3

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
from backend.services.config_generator import (
    MAX_EXTRA_ENDPOINTS,
    generate_config_for_node,
    normalize_extra_endpoints,
)

OWNER = UserInfo(sub="owner-sub", email="owner@example.com", system_role="user")
PUBLIC = "203.0.113.10:4242"


# --- normalize_extra_endpoints --------------------------------------------------------

def test_hostnames_ips_and_private_addresses_are_accepted():
    assert normalize_extra_endpoints(
        ["192.168.1.50:4242", "lh.office.example:4242", "[2001:db8::5]:4242"], PUBLIC, "10.100.0.0/24"
    ) == ["192.168.1.50:4242", "lh.office.example:4242", "[2001:db8::5]:4242"]


def test_repeats_of_the_public_endpoint_and_of_each_other_are_dropped():
    assert normalize_extra_endpoints([PUBLIC, "192.168.1.50:4242", " 192.168.1.50:4242 ", ""], PUBLIC) == [
        "192.168.1.50:4242"
    ]


@pytest.mark.parametrize(
    "bad, match",
    [
        ("192.168.1.50", "port"),
        ("192.168.1.50:0", "port"),
        ("192.168.1.50:99999", "port"),
        ("a:1, b:2", "one endpoint per entry"),
        ("127.0.0.1:4242", "not routable"),
        ("0.0.0.0:4242", "not routable"),
        ("10.100.0.7:4242", "inside the Nebula network"),
        ("bad_host!:4242", "invalid hostname"),
    ],
)
def test_bad_entries_are_rejected(bad, match):
    with pytest.raises(ValueError, match=match):
        normalize_extra_endpoints([bad], PUBLIC, "10.100.0.0/24")


def test_only_alongside_a_public_endpoint():
    with pytest.raises(ValueError, match="Set a public endpoint"):
        normalize_extra_endpoints(["192.168.1.50:4242"], None)
    assert normalize_extra_endpoints([], None) == []


def test_capped():
    many = [f"192.168.1.{i}:4242" for i in range(1, MAX_EXTRA_ENDPOINTS + 2)]
    with pytest.raises(ValueError, match="At most"):
        normalize_extra_endpoints(many, PUBLIC)


# --- API + generated config -------------------------------------------------------------

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
            Node(id=1, network_id=network.id, hostname="office-lh", ip_address="10.100.0.1", groups=[],
                 unsafe_routes=[], is_lighthouse=True, is_relay=True, public_endpoint=PUBLIC),
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
        client.sessions = sessions
        yield client
    await engine.dispose()


async def _static_map(api, node_id: int = 2) -> dict:
    async with api.sessions() as s:
        return yaml.safe_load(await generate_config_for_node(s, node_id))["static_host_map"]


@pytest.mark.asyncio
async def test_peers_get_every_address_in_order(api):
    r = await api.patch("/api/nodes/1", json={"extra_endpoints": ["192.168.1.50:4242"]})
    assert r.status_code == 200, r.text
    assert (await api.get("/api/nodes/1")).json()["extra_endpoints"] == ["192.168.1.50:4242"]
    assert (await _static_map(api))["10.100.0.1"] == [PUBLIC, "192.168.1.50:4242"]


@pytest.mark.asyncio
async def test_unchanged_nodes_keep_a_single_address(api):
    assert (await _static_map(api))["10.100.0.1"] == [PUBLIC]


@pytest.mark.asyncio
async def test_rejected_without_a_public_endpoint_and_when_it_is_cleared(api):
    r = await api.patch("/api/nodes/2", json={"extra_endpoints": ["192.168.1.60:4242"]})
    assert r.status_code == 400 and "public endpoint" in r.json()["detail"]
    assert (await api.patch("/api/nodes/1", json={"extra_endpoints": ["192.168.1.50:4242"]})).status_code == 200
    r = await api.patch("/api/nodes/1", json={"public_endpoint": ""})
    assert r.status_code == 400, "clearing the public endpoint must not strand the additional ones"
    r = await api.patch("/api/nodes/1", json={"public_endpoint": "", "extra_endpoints": [], "is_lighthouse": False,
                                              "is_relay": False})
    assert r.status_code in (200, 409), r.text  # 409: it's the only lighthouse - fine, not our check


@pytest.mark.asyncio
async def test_bad_entry_is_a_400_with_the_reason(api):
    r = await api.patch("/api/nodes/1", json={"extra_endpoints": ["10.100.0.9:4242"]})
    assert r.status_code == 400 and "inside the Nebula network" in r.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_stored_entry_is_skipped_not_fatal(api):
    async with api.sessions() as s:
        node = await s.get(Node, 1)
        node.extra_endpoints = ["no-port-here", "192.168.1.50:4242"]
        await s.commit()
    assert (await _static_map(api))["10.100.0.1"] == [PUBLIC, "192.168.1.50:4242"]


def test_old_database_gains_the_column(tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    from backend import database
    db = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    engine.dispose()
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE nodes DROP COLUMN extra_endpoints")  # a database from before the column
    con.commit()
    con.close()
    monkeypatch.setattr(database, "_db_url", f"sqlite+aiosqlite:///{db}")
    database._run_sqlite_migrations()
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(nodes)")}
    assert "extra_endpoints" in cols
