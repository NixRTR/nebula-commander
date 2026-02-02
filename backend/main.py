"""
Nebula Commander - self-hosted Nebula control plane.

Copyright (c) 2025 NixRTR. MIT License. See LICENSE in the repo root.
"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .api import networks, nodes, certificates, auth, heartbeat, device

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
    await init_db()
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Self-hosted Nebula control plane",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(heartbeat.router)
app.include_router(networks.router)
app.include_router(nodes.router)
app.include_router(certificates.router)
app.include_router(device.router)


@app.get("/api")
async def root():
    """API root."""
    return {
        "name": settings.app_name,
        "version": "0.1.0",
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
