"""
OIDC authentication middleware. Validates JWT from OIDC provider (Authelia, Authentik, etc.)
or from our own JWT secret. When oidc_issuer_url is set, JWTs are validated using the
provider's JWKS; otherwise the configured JWT secret is used.
Also: device tokens (JWT with sub=device, node_id) for dnclient-style enrollment.
"""
import logging
from datetime import datetime, timedelta
from typing import Annotated, Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# Cache for JWKS (issuer URL -> {"keys": [...]})
_jwks_cache: dict[str, dict] = {}
_jwks_cache_issuer: Optional[str] = None


def _fetch_jwks(issuer_url: str) -> dict:
    """Fetch JWKS from OIDC issuer. Caches result."""
    global _jwks_cache_issuer, _jwks_cache
    base = issuer_url.rstrip("/")
    jwks_url = f"{base}/.well-known/jwks.json"
    if _jwks_cache_issuer != jwks_url:
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(jwks_url)
                r.raise_for_status()
                _jwks_cache = r.json()
                _jwks_cache_issuer = jwks_url
        except Exception as e:
            logger.warning("Failed to fetch JWKS from %s: %s", jwks_url, e)
            _jwks_cache = {}
    return _jwks_cache


def _get_signing_key_from_jwks(token: str, issuer_url: str) -> Optional[dict]:
    """Get the signing key for the token from JWKS."""
    try:
        unverified = jwt.get_unverified_header(token)
        kid = unverified.get("kid")
        if not kid:
            return None
        jwks = _fetch_jwks(issuer_url)
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None
    except Exception:
        return None


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate JWT. Uses OIDC JWKS if issuer is set, else JWT secret."""
    try:
        if settings.oidc_issuer_url:
            key_data = _get_signing_key_from_jwks(token, settings.oidc_issuer_url)
            if key_data:
                key = jwk.construct(key_data)
                payload = jwt.decode(
                    token,
                    key,
                    algorithms=["RS256", "RS384", "RS512"],
                    audience=settings.oidc_client_id,
                    options={"verify_aud": bool(settings.oidc_client_id)},
                )
                return payload
            return None
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError:
        return None


class UserInfo(BaseModel):
    """User info from OIDC token."""

    sub: str
    email: Optional[str] = None
    role: str = "user"


async def get_current_user_optional(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(security)
    ] = None,
) -> Optional[UserInfo]:
    """
    Dependency: optional current user from Bearer token.
    Returns None if no token or invalid token.
    """
    if not credentials or not credentials.credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    return UserInfo(
        sub=sub,
        email=payload.get("email"),
        role=payload.get("role", "user"),
    )


async def require_user(
    user: Annotated[Optional[UserInfo], Depends(get_current_user_optional)] = None,
) -> UserInfo:
    """Dependency: require authenticated user. Raises 401 if not logged in."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# --- Device token (for dnclient-style enrollment) ---

def create_device_token(node_id: int) -> str:
    """Create a long-lived JWT for a device (node). Payload: sub=device, node_id=N."""
    exp = datetime.utcnow() + timedelta(days=settings.device_token_expiration_days)
    payload = {"sub": "device", "node_id": node_id, "exp": exp}
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_device_token(token: str) -> Optional[int]:
    """Decode device JWT; return node_id or None."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("sub") != "device":
            return None
        return payload.get("node_id")
    except JWTError:
        return None


async def require_device_token(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(security)
    ] = None,
) -> int:
    """Dependency: require device Bearer token; return node_id. Raises 401 if invalid."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid device token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    node_id = decode_device_token(credentials.credentials)
    if node_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return node_id
