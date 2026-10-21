"""
Each network has its own tun device (Network.tun_dev) so a host can run one nebula per
network: two nebulas asking for the same device name fail with EBUSY on Linux.

- New networks get a generated "nc-<10 random hex>" device.
- Networks that predate the column keep "nebula1", so upgrading renames nothing.
- ncclient before 0.8.0 always gets "nebula1": only clients that send
  X-Ncclient-Features: tun-dev get the network's device.
- An admin-entered name is checked for shape, for names hosts already use (eth0,
  wlp2s0, docker0, ...) and for uniqueness, through POST/PATCH /api/networks.
"""
import re

import pytest
import pytest_asyncio
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api import networks as networks_api
from backend.auth.oidc import UserInfo, require_user
from backend.database import get_session
from backend.models import Base, Network, Node
from backend.services.config_generator import (
    DEFAULT_TUN_DEV,
    TUN_DEV_MAX_LEN,
    build_config,
    client_supports_tun_dev,
    generate_tun_dev,
    validate_tun_dev,
)

OWNER = UserInfo(sub="owner-sub", email="owner@example.com", system_role="user")


GENERATED = re.compile(r"^nc-[0-9a-f]{10}$")


def test_generated_name_is_nc_and_ten_hex_characters():
    dev = generate_tun_dev(set())
    assert GENERATED.match(dev)
    assert len(dev) <= TUN_DEV_MAX_LEN
    assert validate_tun_dev(dev) == dev


def test_generated_name_is_drawn_again_when_taken(monkeypatch):
    draws = iter(["aaaaaaaaaa", "aaaaaaaaaa", "bbbbbbbbbb"])
    monkeypatch.setattr("backend.services.config_generator.secrets.token_hex", lambda n: next(draws))
    assert generate_tun_dev({"nc-aaaaaaaaaa"}) == "nc-bbbbbbbbbb"


@pytest.mark.parametrize(
    "dev",
    ["lo", "eth0", "eth1", "enp3s0", "eno1", "ens33", "enx0123456789ab", "wlan0", "wlp2s0",
     "wwp0s20u4", "docker0", "br-0123456789ab", "veth1a2b3c", "virbr0", "wg0", "tun0",
     "tap1", "tailscale0", "cali1234abcd", "cilium_host", "flannel-1", "kube-ipvs0"],
)
def test_interface_names_hosts_use_are_reserved(dev):
    with pytest.raises(ValueError, match="reserved"):
        validate_tun_dev(dev)


@pytest.mark.parametrize("dev", ["nebula1", "nc-home", "home-lab", "engineering", "branch", "ens-office", "wireguard"])
def test_ordinary_names_are_allowed(dev):
    assert validate_tun_dev(f"  {dev} ") == dev


@pytest.mark.parametrize("dev", ["", "Home", "a" * 16, "-x", "_x", "a b", "a/b", "a:b", "a.b"])
def test_malformed_names_are_rejected(dev):
    with pytest.raises(ValueError, match="lowercase"):
        validate_tun_dev(dev)


def _config(network: Network, **kwargs) -> dict:
    node = Node(id=1, network_id=1, hostname="n1", ip_address="10.100.0.1", groups=[], unsafe_routes=[])
    return yaml.safe_load(build_config(node, network, [], group_firewalls=[], **kwargs))


def test_config_uses_the_network_device():
    assert _config(Network(id=1, name="Home Lab", tun_dev="nc-home-lab"))["tun"]["dev"] == "nc-home-lab"


def test_clients_before_0_8_0_get_nebula1():
    network = Network(id=1, name="Home Lab", tun_dev="nc-home-lab")
    assert _config(network, per_network_tun_dev=False)["tun"]["dev"] == DEFAULT_TUN_DEV


@pytest.mark.parametrize(
    ("header", "supported"),
    [(None, False), ("", False), ("tun-dev", True), ("other, tun-dev", True), ("tun-devx", False)],
)
def test_client_feature_header(header, supported):
    assert client_supports_tun_dev(header) is supported


def test_network_without_a_device_keeps_nebula1():
    assert _config(Network(id=1, name="Home Lab"))["tun"]["dev"] == DEFAULT_TUN_DEV


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _session():
        async with sessions() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app = FastAPI()
    app.include_router(networks_api.router)
    app.dependency_overrides[require_user] = lambda: OWNER
    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.sessions = sessions
        yield client
    await engine.dispose()


async def _create(api, name: str, cidr: str, **extra):
    return await api.post("/api/networks", json={"name": name, "subnet_cidr": cidr, **extra})


@pytest.mark.asyncio
async def test_create_generates_a_unique_device(api):
    a = await _create(api, "customer-network-a", "10.1.0.0/24")
    b = await _create(api, "customer-network-b", "10.2.0.0/24")
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    assert GENERATED.match(a.json()["tun_dev"]) and GENERATED.match(b.json()["tun_dev"])
    assert a.json()["tun_dev"] != b.json()["tun_dev"]


@pytest.mark.asyncio
async def test_create_accepts_a_chosen_device_and_rejects_reserved_or_taken_ones(api):
    r = await _create(api, "home", "10.1.0.0/24", tun_dev="home-lab")
    assert r.status_code == 200, r.text
    assert r.json()["tun_dev"] == "home-lab"

    r = await _create(api, "office", "10.2.0.0/24", tun_dev="eth0")
    assert r.status_code == 400 and "reserved" in r.json()["detail"]

    r = await _create(api, "office", "10.2.0.0/24", tun_dev="home-lab")
    assert r.status_code == 409 and "home-lab" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_changes_the_device_and_renaming_keeps_it(api):
    net = (await _create(api, "home", "10.1.0.0/24")).json()
    other = (await _create(api, "office", "10.2.0.0/24")).json()

    r = await api.patch(f"/api/networks/{net['id']}", json={"name": "house"})
    assert r.status_code == 200 and r.json()["tun_dev"] == net["tun_dev"]

    r = await api.patch(f"/api/networks/{net['id']}", json={"tun_dev": "house"})
    assert r.status_code == 200 and r.json()["tun_dev"] == "house"

    r = await api.patch(f"/api/networks/{other['id']}", json={"tun_dev": "house"})
    assert r.status_code == 409, r.text
    r = await api.patch(f"/api/networks/{other['id']}", json={"tun_dev": "wlp2s0"})
    assert r.status_code == 400, r.text
    assert (await api.get(f"/api/networks/{other['id']}")).json()["tun_dev"] == other["tun_dev"]


@pytest.mark.asyncio
async def test_legacy_networks_may_share_nebula1(api):
    async with api.sessions() as s:
        s.add_all([
            Network(name="old-a", subnet_cidr="10.1.0.0/24", tun_dev=DEFAULT_TUN_DEV),
            Network(name="old-b", subnet_cidr="10.2.0.0/24", tun_dev=DEFAULT_TUN_DEV),
        ])
        await s.commit()

    # nebula1 isn't a "taken" name, so a third network can be set to it too.
    new = (await _create(api, "new", "10.3.0.0/24")).json()
    r = await api.patch(f"/api/networks/{new['id']}", json={"tun_dev": DEFAULT_TUN_DEV})
    assert r.status_code == 200, r.text
