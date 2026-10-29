"""
Server move (backend/api/move.py, backend/middleware/move.py, backend/services/instance_identity.py):
starting one needs reauth + a 2FA code and the new server's real fingerprint, the signed
statement rides on every device response, the instance goes read-only, cancel stops it,
and the move proof a new server gives is checkable against its fingerprint.
"""
import base64
import json

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api import device as device_api
from backend.api import heartbeat as heartbeat_api
from backend.api import move as move_api
from backend.auth import mfa
from backend.auth.oidc import UserInfo, require_device_token, require_user
from backend.auth.reauth import create_reauth_challenge, create_reauth_token, mark_reauth_completed
from backend.config import settings
from backend.database import get_session
from backend.middleware import MoveMiddleware
from backend.middleware import move as move_middleware
from backend.models import Base, Network, Node, User, UserTotp
from backend.services import instance_identity

ADMIN = UserInfo(sub="admin-sub", email="admin@example.com", system_role="system-admin")
SECRET = mfa.new_secret()
NEW_URL = "https://beardedtek.nebulacdr.net"
NEW_FP = "SHA256:" + "A" * 43


def b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessions() as s:
        admin = User(oidc_sub=ADMIN.sub, email=ADMIN.email, system_role="system-admin")
        network = Network(name="office", subnet_cidr="10.100.0.0/24")
        s.add_all([admin, network])
        await s.flush()
        s.add(Node(id=2, network_id=network.id, hostname="laptop", ip_address="10.100.0.2", groups=[],
                   unsafe_routes=[], is_lighthouse=False, is_relay=False))
        await s.commit()

    async def _session():
        async with sessions() as s:
            yield s
            await s.commit()

    instance_identity.reset_cache()
    move_middleware.invalidate()
    mfa._failures.clear()
    saved = (settings.public_url, settings.move_min_wait_hours)
    settings.public_url = "https://nebulacdr.net"
    settings.move_min_wait_hours = 1
    fetched = {"fp": NEW_FP}

    async def fake_fetch(url):
        fetched["url"] = url
        return fetched["fp"]

    monkeypatch.setattr(move_api, "_fetch_fingerprint", fake_fetch)

    app = FastAPI()
    app.add_middleware(MoveMiddleware, session_factory=sessions)
    app.include_router(move_api.router)
    app.include_router(move_api.instance_router)
    app.include_router(device_api.router)
    app.include_router(heartbeat_api.router)
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[require_user] = lambda: ADMIN
    app.dependency_overrides[require_device_token] = lambda: 2

    @app.post("/api/networks")
    async def some_write():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.sessions = sessions
        client.fetched = fetched
        yield client
    settings.public_url, settings.move_min_wait_hours = saved
    instance_identity.reset_cache()
    move_middleware.invalidate()
    await engine.dispose()


async def turn_on_2fa(api) -> None:
    async with api.sessions() as s:
        user = await mfa.user_row(s, ADMIN.sub)
        s.add(UserTotp(user_id=user.id, secret=mfa.store_secret(SECRET), enabled=True))
        await s.commit()


async def reauth(api) -> str:
    async with api.sessions() as s:
        challenge = await create_reauth_challenge(ADMIN.sub, s)
        await mark_reauth_completed(ADMIN.sub, challenge, s)
        await s.commit()
    return create_reauth_token(ADMIN.sub, challenge)


_offset = {"n": -1}


def code() -> str:
    """A code for a newer time step each call (codes can't be reused)."""
    _offset["n"] = min(_offset["n"] + 1, 1)
    return mfa._code(SECRET, mfa.current_step() + _offset["n"])


async def start(api, **overrides):
    _offset["n"] = -1
    if "reauth_token" not in overrides:
        overrides["reauth_token"] = await reauth(api)
    body = {"new_url": NEW_URL, "new_key_fp": NEW_FP, "wait_hours": 24, "totp_code": code(), **overrides}
    return await api.post("/api/admin/move", json=body)


@pytest.mark.asyncio
async def test_fingerprint_is_the_pinned_key(api):
    fp = (await api.get("/api/instance/fingerprint")).json()["fingerprint"]
    key = (await api.get("/api/device/info")).json()["instance_key"]
    assert fp == instance_identity.fingerprint(key)
    assert fp.startswith("SHA256:") and len(fp) == 7 + 43


@pytest.mark.asyncio
async def test_start_needs_2fa(api):
    r = await start(api)
    assert r.status_code == 403
    assert "two-factor" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_fingerprint_mismatch_is_refused_before_reauth_is_used(api):
    await turn_on_2fa(api)
    api.fetched["fp"] = "SHA256:" + "B" * 43
    token = await reauth(api)
    r = await start(api, reauth_token=token)
    assert r.status_code == 400 and "doesn't match" in r.json()["detail"]
    api.fetched["fp"] = NEW_FP
    r = await start(api, reauth_token=token)  # the same reauth still works
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_statement_rides_on_device_responses(api):
    await turn_on_2fa(api)
    assert (await api.get("/api/device/move")).status_code == 204
    r = await start(api)
    assert r.status_code == 200, r.text
    assert api.fetched["url"] == NEW_URL

    resp = await api.get("/api/device/config")  # 404 here (no cert): header even on errors
    header = resp.headers.get(instance_identity.MOVE_HEADER)
    assert header
    assert (await api.get("/api/device/move")).text == header

    body_b64, sig_b64 = header.split(".")
    body = b64url_decode(body_b64)
    key = (await api.get("/api/device/info")).json()["instance_key"]
    Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(b64url_decode(sig_b64), body)
    stmt = json.loads(body)
    assert stmt["new_url"] == NEW_URL and stmt["new_key_fp"] == NEW_FP
    assert stmt["old_url"] == "https://nebulacdr.net" and stmt["v"] == 1
    assert stmt["switch_at"] > stmt["created_at"]

    status = (await api.get("/api/admin/move")).json()
    assert status["move"]["new_url"] == NEW_URL and status["nodes"][0]["hostname"] == "laptop"


@pytest.mark.asyncio
async def test_read_only_while_moving_then_cancel(api):
    await turn_on_2fa(api)
    assert (await api.post("/api/networks")).status_code == 200
    assert (await start(api)).status_code == 200
    r = await api.post("/api/networks")
    assert r.status_code == 423 and NEW_URL in r.json()["detail"]
    # devices keep reporting while moving
    r = await api.post("/api/nodes/2/heartbeat", json={"move_ready": True, "move_state": "pending"})
    assert r.status_code == 200, r.text
    assert (await start(api)).status_code == 423  # no second move while one is running

    r = await api.post("/api/admin/move/cancel", json={"reauth_token": await reauth(api), "totp_code": code()})
    assert r.status_code == 200, r.text
    assert (await api.post("/api/networks")).status_code == 200
    assert instance_identity.MOVE_HEADER not in (await api.get("/api/device/config")).headers
    nodes = (await api.get("/api/admin/move")).json()["nodes"]
    assert nodes[0]["move_ready"] is True and nodes[0]["move_state"] == "pending"


@pytest.mark.asyncio
async def test_bad_destinations(api):
    await turn_on_2fa(api)
    assert (await start(api, new_url="http://plain.example.com")).status_code == 400
    assert (await start(api, new_url="https://nebulacdr.net")).status_code == 400
    assert (await start(api, new_url="https://x.example.com/some/path")).status_code == 400
    assert (await start(api, wait_hours=0)).status_code == 400
    assert (await start(api, wait_hours=73)).status_code == 400
    own = (await api.get("/api/instance/fingerprint")).json()["fingerprint"]
    api.fetched["fp"] = own
    assert (await start(api, new_key_fp=own)).status_code == 400


@pytest.mark.asyncio
async def test_ip_destination_is_allowed(api):
    await turn_on_2fa(api)
    r = await start(api, new_url="https://203.0.113.5:8443")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_move_proof_checks_out_against_the_fingerprint(api):
    r = await api.post("/api/device/move-proof", json={"nonce": "n" * 32, "new_url": NEW_URL})
    assert r.status_code == 200, r.text
    proof = r.json()
    fp = (await api.get("/api/instance/fingerprint")).json()["fingerprint"]
    assert instance_identity.fingerprint(proof["public_key"]) == fp
    Ed25519PublicKey.from_public_bytes(base64.b64decode(proof["public_key"])).verify(
        b64url_decode(proof["signature"]), instance_identity.proof_message("n" * 32, 2, NEW_URL)
    )
    assert (await api.post("/api/device/move-proof", json={"nonce": "short", "new_url": NEW_URL})).status_code == 400


@pytest.mark.asyncio
async def test_responder_file(api):
    await turn_on_2fa(api)
    assert (await start(api, keep_days=30)).status_code == 200
    data = (await api.get("/api/admin/move/responder")).json()
    assert data["new_url"] == NEW_URL and data["admin_emails"] == ["admin@example.com"]
    assert data["statement"] == (await api.get("/api/device/move")).text
    assert data["recommended_until"] > data["switch_at"]


def test_registrable_domain():
    rd = move_api.registrable_domain
    assert rd("beardedtek.nebulacdr.net") == "nebulacdr.net"
    assert rd("nebulacdr.net") == "nebulacdr.net"
    assert rd("nc.example.co.uk") == "example.co.uk"
    assert rd("203.0.113.5") is None
    assert rd("[2001:db8::1]") is None
