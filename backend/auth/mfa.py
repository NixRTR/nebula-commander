"""
TOTP two-factor login (RFC 6238: SHA-1, 6 digits, 30 s steps - what every authenticator
app speaks) and the session-token states that go with it.

Session tokens minted by /api/auth/callback and /api/auth/dev-token carry an "mfa" claim:
  "ok"      second factor checked at login
  "none"    the user has no 2FA (only accepted while it isn't required)
  "verify"  pending: 2FA enabled, waiting for a code     (only /api/auth/2fa/* accepts it)
  "setup"   pending: 2FA required but not set up yet     (only /api/auth/2fa/* accepts it)
Tokens without the claim (issued before 0.9.0, or straight from the IdP) count as "none".
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote, urlencode

from fastapi import HTTPException, status
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import User, UserRecoveryCode, UserTotp
from ..services.encryption import decrypt_to_str, encrypt_to_str

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
ISSUER = "Nebula Commander"
RECOVERY_CODE_COUNT = 10
PENDING_MINUTES = 15
PENDING_STATES = ("verify", "setup")

# Wrong codes per user before a pause (per process, like the rate limiter).
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 900
_failures: dict[int, list[float]] = defaultdict(list)


# --- TOTP ---

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(now: Optional[float] = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def otpauth_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    query = urlencode({"secret": secret, "issuer": ISSUER, "algorithm": "SHA1",
                       "digits": DIGITS, "period": STEP_SECONDS})
    return f"otpauth://totp/{label}?{query}"


def matching_step(secret: str, code: str, after_step: Optional[int], now: Optional[float] = None) -> Optional[int]:
    """The time step `code` belongs to (within the allowed drift), newer than after_step."""
    code = "".join(code.split())
    if len(code) != DIGITS or not code.isdigit():
        return None
    base = current_step(now)
    for step in range(base - DRIFT_STEPS, base + DRIFT_STEPS + 1):
        if after_step is not None and step <= after_step:
            continue
        if hmac.compare_digest(_code(secret, step), code):
            return step
    return None


# --- recovery codes ---

def _hash_code(code: str) -> str:
    return hashlib.sha256("".join(code.split()).replace("-", "").upper().encode("ascii")).hexdigest()


def _new_recovery_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
    raw = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


async def replace_recovery_codes(session: AsyncSession, user_id: int) -> list[str]:
    for old in (await session.execute(
        select(UserRecoveryCode).where(UserRecoveryCode.user_id == user_id)
    )).scalars().all():
        await session.delete(old)
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        session.add(UserRecoveryCode(user_id=user_id, code_hash=_hash_code(code)))
    await session.flush()
    return codes


async def unused_recovery_codes(session: AsyncSession, user_id: int) -> int:
    rows = (await session.execute(
        select(UserRecoveryCode).where(UserRecoveryCode.user_id == user_id, UserRecoveryCode.used_at.is_(None))
    )).scalars().all()
    return len(rows)


# --- per-user state ---

async def user_row(session: AsyncSession, sub: str, email: Optional[str] = None) -> User:
    """The users row for sub; created if missing (dev-token logins have none)."""
    user = await session.scalar(select(User).where(User.oidc_sub == sub))
    if user is None:
        user = User(oidc_sub=sub, email=email)
        session.add(user)
        await session.flush()
    return user


async def totp_row(session: AsyncSession, user_id: int) -> Optional[UserTotp]:
    return await session.scalar(select(UserTotp).where(UserTotp.user_id == user_id))


async def enabled_for_sub(session: AsyncSession, sub: str) -> bool:
    row = await session.scalar(
        select(UserTotp.enabled).join(User, User.id == UserTotp.user_id).where(User.oidc_sub == sub)
    )
    return bool(row)


def _locked(user_id: int) -> bool:
    now = time.monotonic()
    recent = [t for t in _failures[user_id] if now - t < FAILURE_WINDOW_SECONDS]
    _failures[user_id] = recent
    return len(recent) >= MAX_FAILURES


async def check_code(session: AsyncSession, user_id: int, code: str, *, allow_recovery: bool = True,
                     totp: Optional[UserTotp] = None) -> bool:
    """True when `code` is a current TOTP code (not used before) or an unused recovery
    code for this user. A pending secret (setup not confirmed yet) is checked when
    passed as `totp`. Too many wrong codes lock the user out for a while (429)."""
    if _locked(user_id):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Too many wrong codes. Wait a few minutes and try again.")
    row = totp if totp is not None else await totp_row(session, user_id)
    code = (code or "").strip()
    if row is not None and (row.enabled or totp is not None):
        step = matching_step(decrypt_to_str(row.secret), code, row.last_step)
        if step is not None:
            row.last_step = step
            await session.flush()
            _failures.pop(user_id, None)
            return True
    if allow_recovery and row is not None and row.enabled and len(code.replace("-", "").strip()) == 10:
        hashed = _hash_code(code)
        rec = await session.scalar(select(UserRecoveryCode).where(
            UserRecoveryCode.user_id == user_id,
            UserRecoveryCode.code_hash == hashed,
            UserRecoveryCode.used_at.is_(None),
        ))
        if rec is not None:
            rec.used_at = datetime.utcnow()
            await session.flush()
            _failures.pop(user_id, None)
            return True
    _failures[user_id].append(time.monotonic())
    return False


async def require_code(session: AsyncSession, sub: str, code: Optional[str]) -> None:
    """For sensitive actions (moving the instance): the acting user must have 2FA and
    give a current code. Raises 403 otherwise."""
    user = await session.scalar(select(User).where(User.oidc_sub == sub))
    row = await totp_row(session, user.id) if user else None
    if row is None or not row.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Set up two-factor authentication first (Settings > Security).")
    if not await check_code(session, user.id, code or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Wrong or expired two-factor code")


def store_secret(secret: str) -> str:
    return encrypt_to_str(secret)


def reveal_secret(row: UserTotp) -> str:
    return decrypt_to_str(row.secret)


# --- session tokens ---

def mint_session_token(claims: dict, mfa: str) -> str:
    """Our session JWT with claims (sub, email, name, role, system_role) and an mfa state.
    Pending states get a short lifetime."""
    minutes = PENDING_MINUTES if mfa in PENDING_STATES else settings.jwt_expiration_minutes
    payload = {k: v for k, v in claims.items() if k not in ("exp", "iat", "mfa", "reauth", "challenge")}
    payload["mfa"] = mfa
    payload["exp"] = datetime.utcnow() + timedelta(minutes=minutes)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def login_mfa_state(session: AsyncSession, sub: str) -> str:
    """The mfa claim a fresh login gets."""
    if await enabled_for_sub(session, sub):
        return "verify"
    return "setup" if settings.require_mfa else "none"
