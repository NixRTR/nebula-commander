"""Auth API: login and dev token for development."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..auth.oidc import get_current_user_optional, UserInfo
from jose import jwt

router = APIRouter(prefix="/api/auth", tags=["auth"])


class DevTokenResponse(BaseModel):
    token: str
    expires_in: int


@router.get("/dev-token", response_model=DevTokenResponse)
async def dev_token(
    user: Optional[UserInfo] = Depends(get_current_user_optional),
):
    """
    Return a JWT for development when debug is enabled or when OIDC is not configured.
    When OIDC is not set, this allows the UI to work in standalone/Docker mode.
    No authentication required. Disabled in production when OIDC is configured.
    """
    # Allow when debug is on, or when no OIDC (standalone mode)
    if not settings.debug and settings.oidc_issuer_url:
        raise HTTPException(status_code=404, detail="Not found")
    expires = datetime.utcnow() + timedelta(minutes=settings.jwt_expiration_minutes)
    payload = {
        "sub": "dev",
        "email": "dev@localhost",
        "role": "admin",
        "exp": expires,
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return DevTokenResponse(
        token=token,
        expires_in=settings.jwt_expiration_minutes * 60,
    )


@router.get("/me")
async def me(current_user: UserInfo = Depends(get_current_user_optional)):
    """Return current user info if authenticated."""
    if current_user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "sub": current_user.sub,
        "email": current_user.email,
        "role": current_user.role,
    }
