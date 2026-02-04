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
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo
from ..config import settings
from ..database import get_session
from ..models import Certificate, EnrollmentCode, Network, NetworkConfig, Node
from ..services.config_generator import generate_config_for_node
from ..services.ip_allocator import IPAllocator
from ..services.cert_manager import CertManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


class NodeUpdate(BaseModel):
    """One group per node. Pass a single group name or null to clear."""

    group: Optional[str] = None
    is_lighthouse: Optional[bool] = None
    is_relay: Optional[bool] = None
    public_endpoint: Optional[str] = None
    lighthouse_options: Optional[dict[str, Any]] = None
    logging_options: Optional[dict[str, Any]] = None
    punchy_options: Optional[dict[str, Any]] = None


class NodeResponse(BaseModel):
    id: int
    network_id: int
    hostname: str
    ip_address: Optional[str] = None
    cert_fingerprint: Optional[str] = None
    groups: list = []
    is_lighthouse: bool = False
    is_relay: bool = False
    public_endpoint: Optional[str] = None
    lighthouse_options: Optional[dict[str, Any]] = None
    logging_options: Optional[dict[str, Any]] = None
    punchy_options: Optional[dict[str, Any]] = None
    status: str = "pending"
    last_seen: Optional[str] = None
    first_polled_at: Optional[str] = None
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
            is_relay=n.is_relay,
            public_endpoint=n.public_endpoint,
            lighthouse_options=n.lighthouse_options,
            logging_options=n.logging_options,
            punchy_options=n.punchy_options,
            status=n.status,
            last_seen=n.last_seen.isoformat() if n.last_seen else None,
            first_polled_at=n.first_polled_at.isoformat() if n.first_polled_at else None,
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
    host_key_path = Path(settings.cert_store_path) / str(node.network_id) / "hosts" / f"{node.hostname}.key"
    ca_path = Path(network.ca_cert_path)
    if not ca_path.exists():
        raise HTTPException(status_code=404, detail="CA certificate file not found")
    ca_content = ca_path.read_text()
    host_cert_content = host_cert_path.read_text()
    if host_key_path.exists():
        host_key_content = host_key_path.read_text()
        readme = "host.key is included in this zip.\n"
    else:
        host_key_content = None
        readme = "Use the host.key you saved when creating this certificate.\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ca.crt", ca_content)
        zf.writestr("host.crt", host_cert_content)
        if host_key_content is not None:
            zf.writestr("host.key", host_key_content)
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
        is_relay=node.is_relay,
        public_endpoint=node.public_endpoint,
        lighthouse_options=node.lighthouse_options,
        logging_options=node.logging_options,
        punchy_options=node.punchy_options,
        status=node.status,
        last_seen=node.last_seen.isoformat() if node.last_seen else None,
        first_polled_at=node.first_polled_at.isoformat() if node.first_polled_at else None,
        created_at=node.created_at.isoformat() if node.created_at else "",
    )


@router.patch("/{node_id}")
async def update_node(
    node_id: int,
    body: NodeUpdate,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Update node group (single), lighthouse flag, public endpoint, or lighthouse options."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if body.group is not None:
        node.groups = [body.group] if (body.group and body.group.strip()) else []
    if body.is_lighthouse is not None:
        if body.is_lighthouse is False and node.is_lighthouse:
            # Cannot remove the only lighthouse
            count_result = await session.execute(
                select(func.count(Node.id)).where(
                    Node.network_id == node.network_id,
                    Node.is_lighthouse.is_(True),
                )
            )
            lighthouse_count = count_result.scalar() or 0
            if lighthouse_count <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot remove the only lighthouse. Designate another node as lighthouse first.",
                )
        node.is_lighthouse = body.is_lighthouse
    if body.is_relay is not None:
        node.is_relay = body.is_relay
    if body.public_endpoint is not None:
        node.public_endpoint = body.public_endpoint.strip() or None
    if body.lighthouse_options is not None:
        node.lighthouse_options = body.lighthouse_options
    if body.logging_options is not None:
        node.logging_options = body.logging_options
    if body.punchy_options is not None:
        node.punchy_options = body.punchy_options
    await session.flush()
    return {"ok": True}


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: int,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete a node: release IP, remove host cert/key files, delete related records and node."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    if node.is_lighthouse:
        count_result = await session.execute(
            select(func.count(Node.id)).where(
                Node.network_id == node.network_id,
                Node.is_lighthouse.is_(True),
            )
        )
        lighthouse_count = count_result.scalar() or 0
        if lighthouse_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete the only lighthouse. Designate another node as lighthouse first, or delete the network.",
            )

    # 1. Release the allocated IP
    if node.ip_address:
        ip_allocator = IPAllocator(session)
        await ip_allocator.release(node.network_id, node.ip_address)

    # 2. Remove host cert/key files from disk
    hosts_dir = Path(settings.cert_store_path) / str(node.network_id) / "hosts"
    for ext in (".crt", ".key"):
        p = hosts_dir / f"{node.hostname}{ext}"
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass

    # 3. Delete related records (certificates, network_configs, enrollment_codes)
    await session.execute(delete(Certificate).where(Certificate.node_id == node_id))
    await session.execute(delete(NetworkConfig).where(NetworkConfig.node_id == node_id))
    await session.execute(delete(EnrollmentCode).where(EnrollmentCode.node_id == node_id))

    # 4. Delete the node
    await session.delete(node)
    await session.flush()
    return None


@router.post("/{node_id}/revoke-certificate")
async def revoke_node_certificate(
    node_id: int,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Revoke the node's certificate and take it offline. Node record is kept; can re-enroll later."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Mark all certificates for this node as revoked
    await session.execute(
        update(Certificate).where(Certificate.node_id == node_id).values(revoked_at=datetime.utcnow())
    )
    await session.flush()

    # Release IP and remove host cert/key files
    if node.ip_address:
        ip_allocator = IPAllocator(session)
        await ip_allocator.release(node.network_id, node.ip_address)
        hosts_dir = Path(settings.cert_store_path) / str(node.network_id) / "hosts"
        for ext in (".crt", ".key"):
            p = hosts_dir / f"{node.hostname}{ext}"
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    node.ip_address = None
    node.public_key = None
    node.cert_fingerprint = None
    node.status = "revoked"
    await session.flush()
    return {"ok": True}


@router.post("/{node_id}/re-enroll")
async def reenroll_node(
    node_id: int,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Revoke existing certificate (if any) and issue a new one for this node. Returns success; frontend creates enrollment code."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # If node has a certificate, revoke it first (mark certs, release IP, remove files, clear node fields)
    if node.ip_address:
        await session.execute(
            update(Certificate).where(Certificate.node_id == node_id).values(revoked_at=datetime.utcnow())
        )
        await session.flush()
        ip_allocator = IPAllocator(session)
        await ip_allocator.release(node.network_id, node.ip_address)
        hosts_dir = Path(settings.cert_store_path) / str(node.network_id) / "hosts"
        for ext in (".crt", ".key"):
            p = hosts_dir / f"{node.hostname}{ext}"
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        node.ip_address = None
        node.public_key = None
        node.cert_fingerprint = None
        await session.flush()

    # Load network and create new certificate for existing node
    net_result = await session.execute(select(Network).where(Network.id == node.network_id))
    network = net_result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")

    cert_manager = CertManager(session)
    await cert_manager.create_host_certificate_for_existing_node(node, network)
    await session.flush()
    return {"ok": True, "node_id": node.id}
