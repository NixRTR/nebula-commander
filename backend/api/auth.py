"""Auth API: login and dev token for development."""
import base64
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode, urlparse

import httpx
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.config import Config

from ..config import settings
from ..auth.oidc import get_current_user_optional, require_user, UserInfo
from ..auth.reauth import create_reauth_challenge, mark_reauth_completed, create_reauth_token
from ..database import get_session
from ..models.db import User
from ..services.audit import get_client_ip, log_audit
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# OAuth client setup
oauth = OAuth()


def get_safe_redirect_url(request: Request) -> str:
    """
    Get a safe redirect URL for OAuth/OIDC callbacks.
    
    Prevents open redirect vulnerabilities by:
    1. Using OIDC redirect URI as primary source of truth
    2. Validating against allowed_redirect_hosts whitelist
    3. Falling back to request host only if explicitly allowed
    
    Returns the frontend base URL (scheme + host).
    """
    # Primary source: derive from OIDC redirect URI
    if settings.oidc_redirect_uri:
        parsed = urlparse(settings.oidc_redirect_uri)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        return base_url
    
    # Secondary: check if we have an allowed hosts whitelist
    if settings.allowed_redirect_hosts:
        request_host = request.headers.get("host", request.url.netloc)
        
        # Validate request host against whitelist
        for allowed_host in settings.allowed_redirect_hosts:
            if request_host == allowed_host or request_host.startswith(f"{allowed_host}:"):
                return f"{request.url.scheme}://{request_host}"
        
        # Host not in whitelist - use first allowed host as fallback
        logger.warning(
            "Request host %s not in allowed_redirect_hosts, using first allowed host",
            request_host
        )
        return f"{request.url.scheme}://{settings.allowed_redirect_hosts[0]}"
    
    # Fallback: use request host (less secure, but maintains backward compatibility)
    # This should only happen in development when OIDC is not configured
    request_host = request.headers.get("host", request.url.netloc)
    logger.warning(
        "No redirect validation configured (oidc_redirect_uri or allowed_redirect_hosts empty), "
        "using request host: %s",
        request_host
    )
    return f"{request.url.scheme}://{request_host}"


def get_oauth_client():
    """Get or create OAuth client for OIDC."""
    if not settings.oidc_issuer_url:
        return None
    
    # Register OAuth client if not already registered
    if not hasattr(oauth, 'keycloak'):
        # Use public issuer URL for discovery when set so the browser redirect (login)
        # goes to the correct host:port; otherwise use internal issuer URL.
        issuer_for_discovery = settings.oidc_public_issuer_url or settings.oidc_issuer_url
        well_known_url = f"{issuer_for_discovery.rstrip('/')}/.well-known/openid-configuration"

        oauth.register(
            name='keycloak',
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=well_known_url,
            client_kwargs={
                'scope': settings.oidc_scopes,
            }
        )
    return oauth.keycloak


class DevTokenResponse(BaseModel):
    token: str
    expires_in: int


@router.get("/dev-token", response_model=DevTokenResponse)
async def dev_token(
    request: Request,
    user: Optional[UserInfo] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_session),
):
    """
    Return a JWT for development when debug is enabled or when OIDC is not configured.
    When OIDC is not set, this allows the UI to work in standalone/Docker mode.
    No authentication required. Disabled in production when OIDC is configured.
    
    WARNING: This endpoint grants full admin access without authentication.
    Only use in development or when OIDC is not configured.
    """
    # Allow when debug is on, or when no OIDC (standalone mode)
    if not settings.debug and settings.oidc_issuer_url:
        raise HTTPException(status_code=404, detail="Not found")
    
    # Log warning when dev-token is accessed
    # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
    # This is intentional security logging, not a credential leak. "DEV-TOKEN" is a label, not an actual token.
    logger.warning(
        "DEV-TOKEN accessed from %s - granting admin access without authentication",
        request.client.host if request.client else "unknown"
    )
    expires = datetime.utcnow() + timedelta(minutes=settings.jwt_expiration_minutes)
    payload = {
        "sub": "dev",
        "email": "dev@localhost",
        "role": "system-admin",
        "system_role": "system-admin",
        "exp": expires,
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    await log_audit(
        session,
        "auth_dev_token",
        actor_identifier="dev",
        client_ip=get_client_ip(request),
    )
    await session.commit()
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
        "system_role": current_user.system_role,
    }


@router.get("/login")
async def login(request: Request):
    """
    Redirect to OIDC provider (Keycloak) for authentication.
    Only available when OIDC is configured.
    """
    if not settings.oidc_issuer_url:
        raise HTTPException(
            status_code=501,
            detail="OIDC not configured. Use /api/auth/dev-token for development."
        )
    
    client = get_oauth_client()
    if not client:
        raise HTTPException(status_code=500, detail="OAuth client not initialized")
    
    redirect_uri = settings.oidc_redirect_uri or request.url_for('callback')
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request, session: AsyncSession = Depends(get_session)):
    """
    OAuth callback endpoint. Exchange authorization code for tokens,
    validate the ID token, and create a JWT for the frontend.
    """
    if not settings.oidc_issuer_url:
        raise HTTPException(status_code=501, detail="OIDC not configured")
    
    client = get_oauth_client()
    if not client:
        raise HTTPException(status_code=500, detail="OAuth client not initialized")
    
    client_ip = get_client_ip(request)
    try:
        # Exchange authorization code for tokens
        token = await client.authorize_access_token(request)
        
        # Get user info from ID token or userinfo endpoint
        user_info = token.get('userinfo')
        if not user_info:
            # Parse ID token if userinfo not included
            id_token = token.get('id_token')
            if id_token:
                user_info = id_token
            else:
                # Fetch from userinfo endpoint
                user_info = await client.userinfo(token=token)
        
        # Extract roles from Keycloak token
        resource_access = user_info.get("resource_access", {})
        client_roles = resource_access.get(settings.oidc_client_id, {}).get("roles", [])
        
        # Map to system role (only system-admin is elevated; network ownership is per-network in backend)
        system_role = "user"  # default
        if "system-admin" in client_roles:
            system_role = "system-admin"
        
        # Create our own JWT for the frontend
        expires = datetime.utcnow() + timedelta(minutes=settings.jwt_expiration_minutes)
        payload = {
            "sub": user_info.get("sub"),
            "email": user_info.get("email"),
            "name": user_info.get("name", user_info.get("preferred_username")),
            "role": system_role,  # Legacy field for backward compatibility
            "system_role": system_role,
            "exp": expires,
        }
        
        our_token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        
        # Get or create user and log login success
        oidc_sub = user_info.get("sub")
        email = user_info.get("email") or user_info.get("preferred_username") or "unknown"
        user_result = await session.execute(select(User).where(User.oidc_sub == oidc_sub))
        db_user = user_result.scalar_one_or_none()
        if not db_user:
            db_user = User(oidc_sub=oidc_sub, email=email, system_role=system_role)
            session.add(db_user)
            await session.flush()
        await log_audit(
            session,
            "auth_login_success",
            resource_type="user",
            resource_id=db_user.id,
            actor_user_id=db_user.id,
            actor_identifier=email,
            client_ip=client_ip,
        )
        await session.commit()
        
        # Redirect to frontend with token in URL query params
        # Use validated redirect URL to prevent open redirect attacks
        frontend_url = get_safe_redirect_url(request)
        redirect_url = f"{frontend_url}/auth/callback?token={our_token}"
        
        return RedirectResponse(url=redirect_url)
        
    except Exception as e:
        # Log error and redirect to login with error
        print(f"OAuth callback error: {e}")
        import traceback
        traceback.print_exc()
        await log_audit(
            session,
            "auth_login_failure",
            result="failure",
            actor_identifier="unknown",
            details={"reason": "oauth_error"},
            client_ip=client_ip,
        )
        await session.commit()
        # Use validated redirect URL to prevent open redirect attacks
        frontend_url = get_safe_redirect_url(request)
        error_url = f"{frontend_url}/login?error=auth_failed"
        return RedirectResponse(url=error_url)


@router.get("/logout")
async def logout(request: Request, session: AsyncSession = Depends(get_session)):
    """
    Logout from OIDC provider (Keycloak) and clear session.
    Redirects to Keycloak logout endpoint.
    """
    await log_audit(
        session,
        "auth_logout",
        actor_identifier="unknown",
        client_ip=get_client_ip(request),
    )
    await session.commit()
    if not settings.oidc_issuer_url:
        # No OIDC, just redirect to frontend
        frontend_url = get_safe_redirect_url(request)
        return RedirectResponse(url=frontend_url)
    
    # Construct Keycloak logout URL using public issuer URL (browser-accessible)
    # Format: {issuer}/protocol/openid-connect/logout?post_logout_redirect_uri={frontend}&client_id={client_id}
    frontend_url = get_safe_redirect_url(request)
    
    # Use public issuer URL if set, otherwise fall back to regular issuer URL
    issuer_url = settings.oidc_public_issuer_url or settings.oidc_issuer_url
    
    # Keycloak requires post_logout_redirect_uri (not redirect_uri) and client_id
    logout_params = urlencode({
        'post_logout_redirect_uri': frontend_url,
        'client_id': settings.oidc_client_id,
    })
    logout_url = f"{issuer_url}/protocol/openid-connect/logout?{logout_params}"
    
    return RedirectResponse(url=logout_url)


class ReauthChallengeResponse(BaseModel):
    challenge: str
    reauth_url: str


@router.post("/reauth/challenge", response_model=ReauthChallengeResponse)
async def create_reauth(
    request: Request,
    user: UserInfo = Depends(require_user),
):
    """
    Create a reauthentication challenge for critical operations.
    Returns a challenge token and URL to redirect to for reauthentication.
    """
    challenge = create_reauth_challenge(user.sub)
    
    if not settings.oidc_issuer_url:
        # No OIDC, return a simple challenge (for dev mode)
        host = request.headers.get("host", request.url.netloc)
        reauth_url = f"{request.url.scheme}://{host}/auth/reauth/complete?challenge={challenge}"
        return ReauthChallengeResponse(
            challenge=challenge,
            reauth_url=reauth_url
        )
    
    reauth_redirect_uri = _get_reauth_redirect_uri(request)

    # Use Keycloak authorize endpoint with prompt=login; challenge is passed as state (not in redirect_uri)
    issuer_url = settings.oidc_public_issuer_url or settings.oidc_issuer_url
    auth_params = urlencode({
        'client_id': settings.oidc_client_id,
        'redirect_uri': reauth_redirect_uri,
        'response_type': 'code',
        'scope': settings.oidc_scopes,
        'prompt': 'login',  # Force reauthentication
        'state': challenge,
    })
    reauth_url = f"{issuer_url}/protocol/openid-connect/auth?{auth_params}"
    
    return ReauthChallengeResponse(
        challenge=challenge,
        reauth_url=reauth_url
    )


def _get_reauth_redirect_uri(request: Request) -> str:
    """Same redirect_uri as used when building the reauth auth URL (must match for token exchange)."""
    if settings.oidc_redirect_uri:
        return (
            settings.oidc_redirect_uri.rstrip("/").removesuffix("/api/auth/callback")
            + "/api/auth/reauth/callback"
        )
    return str(request.url_for("reauth_callback"))


@router.get("/reauth/callback")
async def reauth_callback(request: Request):
    """
    Reauthentication callback endpoint. Keycloak redirects here with code and state (our challenge).
    We exchange the code for tokens manually (no authlib session) and validate state ourselves.
    """
    challenge = request.query_params.get("state") or ""
    if not challenge:
        frontend_url = get_safe_redirect_url(request)
        return RedirectResponse(url=f"{frontend_url}/reauth/complete?error=missing_state")

    if not settings.oidc_issuer_url:
        # Dev mode: just mark as completed
        mark_reauth_completed("dev", challenge)
        token = create_reauth_token("dev", challenge)
        frontend_url = get_safe_redirect_url(request)
        return RedirectResponse(url=f"{frontend_url}/reauth/complete?token={token}")

    code = request.query_params.get("code")
    if not code:
        frontend_url = get_safe_redirect_url(request)
        return RedirectResponse(url=f"{frontend_url}/reauth/complete?error=missing_code")

    redirect_uri = _get_reauth_redirect_uri(request)
    issuer_base = (settings.oidc_public_issuer_url or settings.oidc_issuer_url or "").rstrip("/")
    token_url = f"{issuer_base}/protocol/openid-connect/token"

    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            token_response = await http_client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": settings.oidc_client_id,
                    "client_secret": settings.oidc_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_response.raise_for_status()
            token_data = token_response.json()
    except Exception as e:
        logger.exception("Reauth token exchange failed: %s", e)
        frontend_url = get_safe_redirect_url(request)
        return RedirectResponse(url=f"{frontend_url}/reauth/complete?error=reauth_failed")

    # Get user sub from id_token (decode payload only; we only need sub to tie to challenge)
    user_sub = None
    id_token = token_data.get("id_token")
    if id_token:
        try:
            parts = id_token.split(".")
            if len(parts) >= 2:
                payload_b64 = parts[1]
                payload_b64 += "=" * (4 - len(payload_b64) % 4)
                payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                user_sub = payload.get("sub")
        except Exception:
            pass
    if not user_sub and token_data.get("access_token"):
        # Fallback: userinfo endpoint
        client = get_oauth_client()
        if client:
            try:
                user_info = await client.userinfo(token=token_data)
                user_sub = user_info.get("sub") if user_info else None
            except Exception:
                pass
    if not user_sub:
        frontend_url = get_safe_redirect_url(request)
        return RedirectResponse(url=f"{frontend_url}/reauth/complete?error=reauth_failed")

    if not mark_reauth_completed(user_sub, challenge):
        frontend_url = get_safe_redirect_url(request)
        return RedirectResponse(url=f"{frontend_url}/reauth/complete?error=invalid_challenge")

    reauth_token = create_reauth_token(user_sub, challenge)
    frontend_url = get_safe_redirect_url(request)
    return RedirectResponse(url=f"{frontend_url}/reauth/complete?token={reauth_token}")
