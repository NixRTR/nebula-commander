"""
Reauthentication flow for critical operations.

Challenge state is stored in the reauth_challenges table (not in-process memory)
so step-up auth works correctly across multiple worker processes: the request
that creates the challenge and the request that later verifies it may land on
different processes.
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.db import ReauthChallenge


async def create_reauth_challenge(user_sub: str, session: AsyncSession) -> str:
    """
    Create a reauthentication challenge for a user. Replaces any existing
    outstanding challenge for the same user (one active challenge per user).

    Args:
        user_sub: User's subject (from OIDC)
        session: Active DB session

    Returns:
        Challenge token to be validated after reauth
    """
    challenge = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=5)

    result = await session.execute(
        select(ReauthChallenge).where(ReauthChallenge.user_sub == user_sub)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = ReauthChallenge(user_sub=user_sub)
        session.add(row)
    row.challenge = challenge
    row.expires_at = expires_at
    row.authenticated_at = None
    await session.flush()

    return challenge


async def mark_reauth_completed(user_sub: str, challenge: str, session: AsyncSession) -> bool:
    """
    Mark a reauthentication as completed.

    Args:
        user_sub: User's subject
        challenge: Challenge token
        session: Active DB session

    Returns:
        True if challenge is valid and marked as completed
    """
    result = await session.execute(
        select(ReauthChallenge).where(ReauthChallenge.user_sub == user_sub)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False

    if row.challenge != challenge:
        return False

    if datetime.utcnow() > row.expires_at:
        await session.delete(row)
        await session.flush()
        return False

    row.authenticated_at = datetime.utcnow()
    await session.flush()
    return True


async def verify_reauth(user_sub: str, challenge: str, session: AsyncSession) -> bool:
    """
    Verify that a user has recently reauthenticated.

    Args:
        user_sub: User's subject
        challenge: Challenge token
        session: Active DB session

    Returns:
        True if user has valid recent reauthentication
    """
    result = await session.execute(
        select(ReauthChallenge).where(ReauthChallenge.user_sub == user_sub)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False

    if row.challenge != challenge:
        return False

    if row.authenticated_at is None:
        return False

    if datetime.utcnow() > row.expires_at:
        await session.delete(row)
        await session.flush()
        return False

    return True


async def clear_reauth_challenge(user_sub: str, session: AsyncSession) -> None:
    """
    Clear a reauthentication challenge after use.

    Args:
        user_sub: User's subject
        session: Active DB session
    """
    await session.execute(delete(ReauthChallenge).where(ReauthChallenge.user_sub == user_sub))
    await session.flush()


def create_reauth_token(user_sub: str, challenge: str) -> str:
    """
    Create a short-lived JWT token for reauthentication verification.

    Args:
        user_sub: User's subject
        challenge: Challenge token

    Returns:
        JWT token
    """
    expires = datetime.utcnow() + timedelta(minutes=5)
    payload = {
        "sub": user_sub,
        "challenge": challenge,
        "reauth": True,
        "exp": expires,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_reauth_token(token: str) -> Optional[dict]:
    """
    Decode and validate a reauthentication token.

    Args:
        token: JWT token

    Returns:
        Token payload if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if not payload.get("reauth"):
            return None
        return payload
    except Exception:
        return None
