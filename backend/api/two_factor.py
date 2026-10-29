"""
Two-factor login with TOTP (backend/auth/mfa.py): any authenticator app works.

Optional per user, unless NEBULA_COMMANDER_REQUIRE_MFA is set: then every login has to
set it up (pending "setup" token) or give a code (pending "verify" token) before the
session token works anywhere but here.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import mfa
from ..auth.oidc import UserInfo, get_login_in_progress
from ..auth.permissions import require_system_admin
from ..auth.reauth import require_reauth
from ..config import settings
from ..database import get_session
from ..models import User, UserRecoveryCode, UserTotp
from ..services import instance_identity
from ..services.audit import get_client_ip, log_audit

router = APIRouter(prefix="/api/auth/2fa", tags=["two-factor"])


class CodeRequest(BaseModel):
    code: str


class DisableRequest(BaseModel):
    code: str
    reauth_token: str


class ResetRequest(BaseModel):
    code: str  # the acting admin's own code
    reauth_token: str


def _full_only(state: str) -> None:
    if state in mfa.PENDING_STATES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Finish signing in first")


@router.get("/status")
async def two_factor_status(
    login: tuple = Depends(get_login_in_progress),
    session: AsyncSession = Depends(get_session),
):
    user_info, state, _ = login
    user = await mfa.user_row(session, user_info.sub, user_info.email)
    row = await mfa.totp_row(session, user.id)
    enabled = bool(row and row.enabled)
    return {
        "enabled": enabled,
        "required": settings.require_mfa,
        "login_state": state,
        "recovery_codes_left": await mfa.unused_recovery_codes(session, user.id) if enabled else 0,
    }


@router.post("/setup")
async def two_factor_setup(
    login: tuple = Depends(get_login_in_progress),
    session: AsyncSession = Depends(get_session),
):
    """Start setup: a new secret to scan. Nothing changes until /confirm gets a code."""
    user_info, state, _ = login
    if state == "verify":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Enter your current code first")
    user = await mfa.user_row(session, user_info.sub, user_info.email)
    row = await mfa.totp_row(session, user.id)
    if row is not None and row.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Two-factor authentication is already on")
    secret = mfa.new_secret()
    if row is None:
        row = UserTotp(user_id=user.id, secret=mfa.store_secret(secret), enabled=False)
        session.add(row)
    else:
        row.secret, row.last_step = mfa.store_secret(secret), None
    await session.commit()
    account = user_info.email or user.email or user_info.sub
    return {"secret": secret, "otpauth_uri": mfa.otpauth_uri(secret, account)}


@router.post("/confirm")
async def two_factor_confirm(
    request: Request,
    body: CodeRequest,
    login: tuple = Depends(get_login_in_progress),
    session: AsyncSession = Depends(get_session),
):
    """Turn 2FA on with a first code from the app. Returns the recovery codes (shown
    once) and a session token that has passed the second factor."""
    user_info, state, claims = login
    if state == "verify":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Enter your current code first")
    user = await mfa.user_row(session, user_info.sub, user_info.email)
    row = await mfa.totp_row(session, user.id)
    if row is None or row.enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start setup first")
    if not await mfa.check_code(session, user.id, body.code, allow_recovery=False, totp=row):
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That code didn't match. Check the time on your phone and try again.")
    row.enabled, row.enabled_at = True, datetime.utcnow()
    codes = await mfa.replace_recovery_codes(session, user.id)
    await log_audit(session, "two_factor_enabled", resource_type="user", resource_id=user.id,
                    actor_user_id=user.id, actor_identifier=user_info.email, client_ip=get_client_ip(request))
    await session.commit()
    return {"recovery_codes": codes, "token": mfa.mint_session_token(claims, "ok")}


@router.post("/verify")
async def two_factor_verify(
    request: Request,
    body: CodeRequest,
    login: tuple = Depends(get_login_in_progress),
    session: AsyncSession = Depends(get_session),
):
    """Finish a login with a code (or a recovery code). Returns the full session token."""
    user_info, state, claims = login
    user = await mfa.user_row(session, user_info.sub, user_info.email)
    row = await mfa.totp_row(session, user.id)
    if row is None or not row.enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Two-factor authentication is not on")
    ok = await mfa.check_code(session, user.id, body.code)
    await log_audit(session, "two_factor_login", resource_type="user", resource_id=user.id,
                    result="success" if ok else "failure", actor_user_id=user.id,
                    actor_identifier=user_info.email, client_ip=get_client_ip(request))
    await session.commit()
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong or expired code")
    left = await mfa.unused_recovery_codes(session, user.id)
    return {"token": mfa.mint_session_token(claims, "ok"), "recovery_codes_left": left}


@router.post("/recovery-codes")
async def two_factor_new_recovery_codes(
    body: CodeRequest,
    login: tuple = Depends(get_login_in_progress),
    session: AsyncSession = Depends(get_session),
):
    """New set of recovery codes (the old ones stop working). Needs a current code."""
    user_info, state, _ = login
    _full_only(state)
    user = await mfa.user_row(session, user_info.sub, user_info.email)
    if not await mfa.check_code(session, user.id, body.code, allow_recovery=False):
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Wrong or expired code")
    codes = await mfa.replace_recovery_codes(session, user.id)
    await session.commit()
    return {"recovery_codes": codes}


async def _remove(session: AsyncSession, user_id: int) -> None:
    row = await mfa.totp_row(session, user_id)
    if row is not None:
        await session.delete(row)
    for rec in (await session.execute(
        select(UserRecoveryCode).where(UserRecoveryCode.user_id == user_id)
    )).scalars().all():
        await session.delete(rec)


async def _refuse_while_moving(session: AsyncSession) -> None:
    if await instance_identity.active_move(session) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Two-factor authentication can't be turned off while this instance is moving")


@router.post("/disable")
async def two_factor_disable(
    request: Request,
    body: DisableRequest,
    login: tuple = Depends(get_login_in_progress),
    session: AsyncSession = Depends(get_session),
):
    user_info, state, claims = login
    _full_only(state)
    if settings.require_mfa:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Two-factor authentication is required on this instance")
    await _refuse_while_moving(session)
    await require_reauth(user_info.sub, body.reauth_token, session)
    user = await mfa.user_row(session, user_info.sub, user_info.email)
    if not await mfa.check_code(session, user.id, body.code):
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Wrong or expired code")
    await _remove(session, user.id)
    await log_audit(session, "two_factor_disabled", resource_type="user", resource_id=user.id,
                    actor_user_id=user.id, actor_identifier=user_info.email, client_ip=get_client_ip(request))
    await session.commit()
    return {"token": mfa.mint_session_token(claims, "none")}


@router.post("/reset/{user_id}")
async def two_factor_reset(
    user_id: int,
    request: Request,
    body: ResetRequest,
    admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    """Admin: remove another user's 2FA (lost phone, no recovery codes). They set it up
    again at their next login when it is required. Needs the admin's reauth and code."""
    target = await session.get(User, user_id)
    if target is None or target.is_placeholder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.oidc_sub == admin.sub:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use Settings > Security for your own account")
    await require_reauth(admin.sub, body.reauth_token, session)
    await mfa.require_code(session, admin.sub, body.code)
    await _remove(session, target.id)
    actor = await session.scalar(select(User.id).where(User.oidc_sub == admin.sub))
    await log_audit(session, "two_factor_reset", resource_type="user", resource_id=target.id,
                    actor_user_id=actor, actor_identifier=admin.email, client_ip=get_client_ip(request))
    await session.commit()
    return {"ok": True}



async def enabled_user_ids(session: AsyncSession) -> set[int]:
    """Users with 2FA on (the Users page shows who hasn't)."""
    rows = (await session.execute(select(UserTotp.user_id).where(UserTotp.enabled.is_(True)))).scalars().all()
    return set(rows)
