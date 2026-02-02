"""Nodes API: list and manage Nebula nodes."""
import io
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo
from ..config import settings
from ..database import get_session
from ..models import Network, Node
from ..services.config_generator import generate_config_for_node

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


class NodeUpdate(BaseModel):
    groups: Optional[list[str]] = None
    is_lighthouse: Optional[bool] = None
    public_endpoint: Optional[str] = None
    lighthouse_options: Optional[dict[str, Any]] = None


class NodeResponse(BaseModel):
    id: int
    network_id: int
    hostname: str
    ip_address: Optional[str] = None
    cert_fingerprint: Optional[str] = None
    groups: list = []
    is_lighthouse: bool = False
    public_endpoint: Optional[str] = None
    lighthouse_options: Optional[dict[str, Any]] = None
    status: str = "pending"
    last_seen: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=list[NodeResponse])
async def list_nodes(
    network_id: Optional[int] = Query(None),
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """List nodes, optionally filtered by network_id."""
    q = select(Node).order_by(Node.id)
    if network_id is not None:
        q = q.where(Node.network_id == network_id)
    result = await session.execute(q)
    nodes = result.scalars().all()
    return [
        NodeResponse(
            id=n.id,
            network_id=n.network_id,
            hostname=n.hostname,
            ip_address=n.ip_address,
            cert_fingerprint=n.cert_fingerprint,
            groups=n.groups or [],
            is_lighthouse=n.is_lighthouse,
            public_endpoint=n.public_endpoint,
            lighthouse_options=n.lighthouse_options,
            status=n.status,
            last_seen=n.last_seen.isoformat() if n.last_seen else None,
            created_at=n.created_at.isoformat() if n.created_at else "",
        )
        for n in nodes
    ]


@router.get("/{node_id}/config")
async def get_node_config(
    node_id: int,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Generate and return Nebula YAML config for this node."""
    yaml_config = await generate_config_for_node(session, node_id)
    if yaml_config is None:
        raise HTTPException(status_code=404, detail="Node not found")
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    filename = f"{node.hostname}.yaml" if node else "config.yaml"
    return Response(
        content=yaml_config,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{node_id}/certs")
async def get_node_certs(
    node_id: int,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Return a ZIP with ca.crt, host.crt, and README for this node."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if not node.ip_address:
        raise HTTPException(
            status_code=404,
            detail="Node has no certificate (no IP assigned). Create a certificate first.",
        )
    result = await session.execute(select(Network).where(Network.id == node.network_id))
    network = result.scalar_one_or_none()
    if not network or not network.ca_cert_path:
        raise HTTPException(status_code=404, detail="Network or CA not found")
    host_cert_path = Path(settings.cert_store_path) / str(node.network_id) / "hosts" / f"{node.hostname}.crt"
    if not host_cert_path.exists():
        raise HTTPException(status_code=404, detail="Host certificate file not found")
    ca_path = Path(network.ca_cert_path)
    if not ca_path.exists():
        raise HTTPException(status_code=404, detail="CA certificate file not found")
    ca_content = ca_path.read_text()
    host_cert_content = host_cert_path.read_text()
    readme = "Use the host.key you saved when creating this certificate.\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ca.crt", ca_content)
        zf.writestr("host.crt", host_cert_content)
        zf.writestr("README.txt", readme)
    buf.seek(0)
    filename = f"node-{node.hostname}-certs.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{node_id}", response_model=NodeResponse)
async def get_node(
    node_id: int,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get a single node by ID."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return NodeResponse(
        id=node.id,
        network_id=node.network_id,
        hostname=node.hostname,
        ip_address=node.ip_address,
        cert_fingerprint=node.cert_fingerprint,
        groups=node.groups or [],
        is_lighthouse=node.is_lighthouse,
        public_endpoint=node.public_endpoint,
        lighthouse_options=node.lighthouse_options,
        status=node.status,
        last_seen=node.last_seen.isoformat() if node.last_seen else None,
        created_at=node.created_at.isoformat() if node.created_at else "",
    )


@router.patch("/{node_id}")
async def update_node(
    node_id: int,
    body: NodeUpdate,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Update node groups, lighthouse flag, public endpoint, or lighthouse options."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if body.groups is not None:
        node.groups = body.groups
    if body.is_lighthouse is not None:
        node.is_lighthouse = body.is_lighthouse
    if body.public_endpoint is not None:
        node.public_endpoint = body.public_endpoint.strip() or None
    if body.lighthouse_options is not None:
        node.lighthouse_options = body.lighthouse_options
    await session.flush()
    return {"ok": True}
