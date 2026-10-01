"""
Devices that keep retrying a rejected token get 429 after a few 401s (ncclient
before v0.7.0 retried in a tight loop); valid tokens and other devices are unaffected.
"""
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api import heartbeat as heartbeat_api
from backend.auth import device_throttle
from backend.auth.device_throttle import RejectedTokenThrottle
from backend.auth.oidc import create_device_token
from backend.database import get_session
from backend.models import Base, Network, Node


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# --- the throttle itself ------------------------------------------------------------

def test_throttles_after_limit_then_recovers():
    clock = Clock()
    th = RejectedTokenThrottle(limit=3, window=60, clock=clock)
    for _ in range(2):
        th.record_rejection("t")
        assert th.retry_after("t") is None
    th.record_rejection("t")
    assert th.retry_after("t") == 60
    clock.t += 45
    assert th.retry_after("t") == 15
    assert th.retry_after("other") is None
    clock.t += 15
    assert th.retry_after("t") is None  # window over: back to plain 401s
    th.record_rejection("t")
    assert th.retry_after("t") is None


def test_rejections_spread_out_never_throttle():
    clock = Clock()
    th = RejectedTokenThrottle(limit=3, window=60, clock=clock)
    for _ in range(10):  # one per poll interval, like a current client restarting
        th.record_rejection("t")
        assert th.retry_after("t") is None
        clock.t += 61


def test_memory_is_bounded():
    clock = Clock()
    th = RejectedTokenThrottle(limit=3, window=60, max_entries=100, clock=clock)
    for i in range(1000):
        th.record_rejection(f"tok{i}")
        clock.t += 0.01
    assert len(th._seen) <= 100


def test_tokens_are_not_stored_as_is():
    th = RejectedTokenThrottle()
    th.record_rejection("secret-token-value")
    assert "secret-token-value" not in th._seen


# --- through a real device endpoint --------------------------------------------------

@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    monkeypatch.setattr(device_throttle, "rejected_device_tokens", RejectedTokenThrottle())
    import backend.auth.oidc as oidc
    monkeypatch.setattr(oidc, "rejected_device_tokens", device_throttle.rejected_device_tokens)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessions() as s:
        network = Network(name="net", subnet_cidr="10.100.0.0/24")
        s.add(network)
        await s.flush()
        s.add(Node(id=2, network_id=network.id, hostname="laptop", ip_address="10.100.0.2", groups=[],
                   unsafe_routes=[], is_lighthouse=False, is_relay=False, device_token_version=2))
        await s.commit()

    async def _session():
        async with sessions() as s:
            yield s
            await s.commit()

    app = FastAPI()
    app.include_router(heartbeat_api.router)
    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await engine.dispose()


async def _beat(api, token):
    return await api.post("/api/nodes/2/heartbeat", json={}, headers={"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_revoked_token_gets_429_after_three_401s(api):
    old = create_device_token(2, 1)  # version 1: superseded (revoked/re-enrolled)
    codes = [(await _beat(api, old)).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]
    r = await _beat(api, old)
    assert 0 < int(r.headers["Retry-After"]) <= 60

    # the device's current token is unaffected
    assert (await _beat(api, create_device_token(2, 2))).status_code == 200


@pytest.mark.asyncio
async def test_garbage_tokens_are_throttled_too(api):
    codes = [(await _beat(api, "not-a-jwt")).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
