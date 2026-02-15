"""
Reauthentication flow for critical operations.
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt

from ..config import settings

# In-memory cache for reauth challenges (sub -> challenge_data)
# In production, this should be Redis or similar
_reauth_challenges: dict[str, dict] = {}


def create_reauth_challenge(user_sub: str) -> str:
    """
    Create a reauthentication challenge for a user.
    
    Args:
        user_sub: User's subject (from OIDC)
    
    Returns:
        Challenge token to be validated after reauth
    """
    challenge = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=5)
    
    _reauth_challenges[user_sub] = {
        "challenge": challenge,
        "expires_at": expires_at,
        "authenticated_at": None,
    }
    
    return challenge


def mark_reauth_completed(user_sub: str, challenge: str) -> bool:
    """
    Mark a reauthentication as completed.
    
    Args:
        user_sub: User's subject
        challenge: Challenge token
    
    Returns:
        True if challenge is valid and marked as completed
    """
    if user_sub not in _reauth_challenges:
        return False
    
    data = _reauth_challenges[user_sub]
    
    # Check if challenge matches and hasn't expired
    if data["challenge"] != challenge:
        return False
    
    if datetime.utcnow() > data["expires_at"]:
        del _reauth_challenges[user_sub]
        return False
    
    # Mark as authenticated
    data["authenticated_at"] = datetime.utcnow()
    return True


def verify_reauth(user_sub: str, challenge: str) -> bool:
    """
    Verify that a user has recently reauthenticated.
    
    Args:
        user_sub: User's subject
        challenge: Challenge token
    
    Returns:
        True if user has valid recent reauthentication
    """
    if user_sub not in _reauth_challenges:
        return False
    
    data = _reauth_challenges[user_sub]
    
    # Check if challenge matches
    if data["challenge"] != challenge:
        return False
    
    # Check if authenticated
    if data["authenticated_at"] is None:
        return False
    
    # Check if still valid (5 minutes from authentication)
    if datetime.utcnow() > data["expires_at"]:
        del _reauth_challenges[user_sub]
        return False
    
    return True


def clear_reauth_challenge(user_sub: str) -> None:
    """
    Clear a reauthentication challenge after use.
    
    Args:
        user_sub: User's subject
    """
    if user_sub in _reauth_challenges:
        del _reauth_challenges[user_sub]


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
