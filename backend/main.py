"""
Nebula Commander - self-hosted Nebula control plane.

Copyright (c) 2025 NixRTR. MIT License. See LICENSE in the repo root.
"""
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .database import init_db
from .api import networks, nodes, certificates, auth, heartbeat, device, users, node_requests, access_grants, invitations, network_permissions, audit, public_config
from .middleware import RateLimitMiddleware

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: init DB on startup."""
    logger.info("Starting %s...", settings.app_name)
    
    # Warn if dev-token is available
    if settings.debug or not settings.oidc_issuer_url:
        logger.warning(
            "⚠️  DEV-TOKEN ENDPOINT ENABLED - Anyone can obtain admin access without authentication!"
        )
        if settings.oidc_issuer_url:
            logger.warning(
                "⚠️  OIDC is configured but DEBUG=true - this is INSECURE for production!"
            )
    
    await init_db()
    yield
    logger.info("Shutting down...")


VERSION = os.getenv("VERSION", "0.1.8")

app = FastAPI(
    title=settings.app_name,
    version=VERSION,
    description="Self-hosted Nebula control plane",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Rate limiting middleware (applied first to catch attacks early)
app.add_middleware(RateLimitMiddleware)

# Session middleware (required for OAuth)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.jwt_secret_key,  # Use same secret as JWT
    session_cookie="nebula_session",
    max_age=3600,  # 1 hour
    same_site="lax",
    https_only=settings.session_https_only,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Warn if CORS is set to allow all origins with credentials
if "*" in settings.cors_origins:
    logger.warning(
        "⚠️  CORS is set to allow ALL origins (*) with credentials - this is INSECURE for production!"
    )

app.include_router(auth.router)
app.include_router(heartbeat.router)
app.include_router(networks.router)
app.include_router(nodes.router)
app.include_router(certificates.router)
app.include_router(device.router)
app.include_router(users.router)
app.include_router(node_requests.router)
app.include_router(access_grants.router)
app.include_router(invitations.router)
app.include_router(network_permissions.router)
app.include_router(audit.router)
app.include_router(public_config.router)


@app.get("/api")
async def root():
    """API root."""
    return {
        "name": settings.app_name,
        "version": VERSION,
        "status": "operational",
    }


@app.get("/api/health")
async def health():
    """Health check."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
