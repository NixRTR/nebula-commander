"""
TOTP two-factor login (backend/auth/mfa.py, backend/api/two_factor.py): setup/confirm,
the pending login states, replay and recovery codes, NEBULA_COMMANDER_REQUIRE_MFA, and
that device and reauth tokens never pass as a user.
"""
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api import auth as auth_api
from backend.api import two_factor as two_factor_api
from backend.auth import mfa
from backend.auth.oidc import create_device_token
from backend.auth.reauth import create_reauth_challenge, create_reauth_token, mark_reauth_completed
from backend.config import settings
from backend.database import get_session
from backend.models import Base, User

CLAIMS = {"sub": "alice-sub", "email": "alice@example.com", "role": "user", "system_role": "user"}


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessions() as s:
        s.add(User(oidc_sub=CLAIMS["sub"], email=CLAIMS["email"]))
        await s.commit()

    async def _session():
        async with sessions() as s:
            yield s
            await s.commit()

    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(two_factor_api.router)
    app.dependency_overrides[get_session] = _session
    saved = settings.require_mfa
    mfa._failures.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.sessions = sessions
        yield client
    settings.require_mfa = saved
    await engine.dispose()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def me(api, token) -> dict:
    return (await api.get("/api/auth/me", headers=bearer(token))).json()


def code_for(secret: str, offset: int = 0) -> str:
    return mfa._code(secret, mfa.current_step() + offset)


async def enable(api) -> tuple[str, str, list[str]]:
    """Turn 2FA on for alice; returns (secret, full token, recovery codes)."""
    token = mfa.mint_session_token(CLAIMS, "none")
    r = await api.post("/api/auth/2fa/setup", headers=bearer(token))
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/Nebula%20Commander%3Aalice%40example.com?secret=")
    r = await api.post("/api/auth/2fa/confirm", json={"code": code_for(secret)}, headers=bearer(token))
    assert r.status_code == 200, r.text
    return secret, r.json()["token"], r.json()["recovery_codes"]


async def reauth_token(api, sub: str) -> str:
    async with api.sessions() as s:
        challenge = await create_reauth_challenge(sub, s)
        await mark_reauth_completed(sub, challenge, s)
        await s.commit()
    return create_reauth_token(sub, challenge)


def test_totp_matches_rfc6238_vector():
    # RFC 6238 appendix B, SHA-1, T=59 -> 94287082 (8 digits); 6-digit form is the last six
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of "12345678901234567890"
    assert mfa._code(secret, 59 // 30) == "287082"
    assert mfa.matching_step(secret, "287082", None, now=59) == 1
    assert mfa.matching_step(secret, "287082", 1, now=59) is None  # already used


@pytest.mark.asyncio
async def test_setup_confirm_turns_old_sessions_off(api):
    old = mfa.mint_session_token(CLAIMS, "none")
    assert (await me(api, old))["authenticated"] is True
    assert (await me(api, old))["two_factor_enabled"] is False
    secret, full, codes = await enable(api)
    assert len(codes) == 10
    # a session that never gave a code no longer works once 2FA is on
    assert (await me(api, old))["authenticated"] is False
    body = await me(api, full)
    assert body["authenticated"] is True and body["two_factor_enabled"] is True


@pytest.mark.asyncio
async def test_confirm_needs_the_right_code(api):
    token = mfa.mint_session_token(CLAIMS, "none")
    secret = (await api.post("/api/auth/2fa/setup", headers=bearer(token))).json()["secret"]
    r = await api.post("/api/auth/2fa/confirm", json={"code": "000000" if code_for(secret) != "000000" else "111111"},
                       headers=bearer(token))
    assert r.status_code == 400
    assert (await me(api, token))["two_factor_enabled"] is False


@pytest.mark.asyncio
async def test_pending_login_needs_a_code(api):
    secret, _, _ = await enable(api)
    async with api.sessions() as s:
        assert await mfa.login_mfa_state(s, CLAIMS["sub"]) == "verify"
    pending = mfa.mint_session_token(CLAIMS, "verify")
    assert (await me(api, pending))["authenticated"] is False
    # setup can't be restarted to dodge the code
    assert (await api.post("/api/auth/2fa/setup", headers=bearer(pending))).status_code == 403
    r = await api.post("/api/auth/2fa/verify", json={"code": code_for(secret)}, headers=bearer(pending))
    assert r.status_code == 401  # same time step as the confirm: a replay
    r = await api.post("/api/auth/2fa/verify", json={"code": code_for(secret, 1)}, headers=bearer(pending))
    assert r.status_code == 200, r.text
    assert (await me(api, r.json()["token"]))["authenticated"] is True


@pytest.mark.asyncio
async def test_recovery_code_works_once(api):
    _, _, codes = await enable(api)
    pending = mfa.mint_session_token(CLAIMS, "verify")
    r = await api.post("/api/auth/2fa/verify", json={"code": codes[0].lower()}, headers=bearer(pending))
    assert r.status_code == 200, r.text
    assert r.json()["recovery_codes_left"] == 9
    r = await api.post("/api/auth/2fa/verify", json={"code": codes[0]}, headers=bearer(pending))
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_codes_lock_out(api):
    secret, _, _ = await enable(api)
    pending = mfa.mint_session_token(CLAIMS, "verify")
    good = {code_for(secret, o) for o in (-1, 0, 1)}
    wrong = next(c for c in ("000000", "111111", "222222", "333333") if c not in good)
    for _ in range(mfa.MAX_FAILURES):
        assert (await api.post("/api/auth/2fa/verify", json={"code": wrong}, headers=bearer(pending))).status_code == 401
    r = await api.post("/api/auth/2fa/verify", json={"code": code_for(secret, 1)}, headers=bearer(pending))
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_require_mfa_forces_setup(api):
    settings.require_mfa = True
    token = mfa.mint_session_token(CLAIMS, "none")
    assert (await me(api, token))["authenticated"] is False  # no "ok" -> not a session
    async with api.sessions() as s:
        assert await mfa.login_mfa_state(s, CLAIMS["sub"]) == "setup"
    pending = mfa.mint_session_token(CLAIMS, "setup")
    secret = (await api.post("/api/auth/2fa/setup", headers=bearer(pending))).json()["secret"]
    r = await api.post("/api/auth/2fa/confirm", json={"code": code_for(secret)}, headers=bearer(pending))
    assert r.status_code == 200, r.text
    full = r.json()["token"]
    assert (await me(api, full))["authenticated"] is True
    r = await api.post("/api/auth/2fa/disable", json={"code": code_for(secret, 1), "reauth_token": "x"},
                       headers=bearer(full))
    assert r.status_code == 403  # required here


@pytest.mark.asyncio
async def test_disable_needs_reauth_and_code(api):
    secret, full, _ = await enable(api)
    r = await api.post("/api/auth/2fa/disable", json={"code": code_for(secret, 1), "reauth_token": "bogus"},
                       headers=bearer(full))
    assert r.status_code == 403
    r = await api.post("/api/auth/2fa/disable",
                       json={"code": code_for(secret, 1), "reauth_token": await reauth_token(api, CLAIMS["sub"])},
                       headers=bearer(full))
    assert r.status_code == 200, r.text
    assert (await me(api, r.json()["token"]))["two_factor_enabled"] is False


@pytest.mark.asyncio
async def test_device_and_reauth_tokens_are_not_users(api):
    assert (await me(api, create_device_token(1, 1)))["authenticated"] is False
    assert (await me(api, create_reauth_token(CLAIMS["sub"], "challenge")))["authenticated"] is False
