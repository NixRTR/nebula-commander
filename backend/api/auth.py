"""Auth API: login and dev token for development."""
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode, urlparse
import logging

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.config import Config

from ..config import settings
from ..auth.oidc import get_current_user_optional, require_user, UserInfo
from ..auth.reauth import create_reauth_challenge, mark_reauth_completed, create_reauth_token
from jose import jwt

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
        # Construct the well-known URL - use the issuer URL as-is since it should be
        # accessible from the backend container (using Docker service name)
        well_known_url = f"{settings.oidc_issuer_url}/.well-known/openid-configuration"
        
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
async def callback(request: Request):
    """
    OAuth callback endpoint. Exchange authorization code for tokens,
    validate the ID token, and create a JWT for the frontend.
    """
    if not settings.oidc_issuer_url:
        raise HTTPException(status_code=501, detail="OIDC not configured")
    
    client = get_oauth_client()
    if not client:
        raise HTTPException(status_code=500, detail="OAuth client not initialized")
    
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
        
        # Map to system role
        system_role = "user"  # default
        if "system-admin" in client_roles:
            system_role = "system-admin"
        elif "network-owner" in client_roles:
            system_role = "network-owner"
        
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
        # Use validated redirect URL to prevent open redirect attacks
        frontend_url = get_safe_redirect_url(request)
        error_url = f"{frontend_url}/login?error=auth_failed"
        return RedirectResponse(url=error_url)


@router.get("/logout")
async def logout(request: Request):
    """
    Logout from OIDC provider (Keycloak) and clear session.
    Redirects to Keycloak logout endpoint.
    """
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
    
    # Construct Keycloak login URL with prompt=login to force reauthentication
    host = request.headers.get("host", request.url.netloc)
    callback_url = f"{request.url.scheme}://{host}/auth/reauth/callback?challenge={challenge}"
    
    # Use Keycloak authorize endpoint with prompt=login
    issuer_url = settings.oidc_public_issuer_url or settings.oidc_issuer_url
    auth_params = urlencode({
        'client_id': settings.oidc_client_id,
        'redirect_uri': callback_url,
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


@router.get("/reauth/callback")
async def reauth_callback(request: Request, challenge: str):
    """
    Reauthentication callback endpoint. Validates that user reauthenticated
    and returns a reauth token to the frontend.
    """
    if not settings.oidc_issuer_url:
        # Dev mode: just mark as completed
        # In production, this should validate the user actually reauthenticated
        mark_reauth_completed("dev", challenge)
        token = create_reauth_token("dev", challenge)
        frontend_url = get_safe_redirect_url(request)
        return RedirectResponse(url=f"{frontend_url}/reauth/complete?token={token}")
    
    client = get_oauth_client()
    if not client:
        raise HTTPException(status_code=500, detail="OAuth client not initialized")
    
    try:
        # Exchange authorization code for tokens
        token = await client.authorize_access_token(request)
        
        # Get user info
        user_info = token.get('userinfo')
        if not user_info:
            id_token = token.get('id_token')
            if id_token:
                user_info = id_token
            else:
                user_info = await client.userinfo(token=token)
        
        user_sub = user_info.get("sub")
        
        # Mark reauthentication as completed
        if mark_reauth_completed(user_sub, challenge):
            # Create reauth token
            reauth_token = create_reauth_token(user_sub, challenge)
            
            # Redirect to frontend with reauth token
            frontend_url = get_safe_redirect_url(request)
            return RedirectResponse(url=f"{frontend_url}/reauth/complete?token={reauth_token}")
        else:
            raise HTTPException(status_code=400, detail="Invalid or expired challenge")
            
    except Exception as e:
        print(f"Reauth callback error: {e}")
        import traceback
        traceback.print_exc()
        frontend_url = get_safe_redirect_url(request)
        return RedirectResponse(url=f"{frontend_url}?error=reauth_failed")
