"""Nodes API: list and manage Nebula nodes."""
import io
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo
from ..auth.permissions import get_user_nodes
from ..auth.reauth import clear_reauth_challenge, decode_reauth_token, verify_reauth
from ..config import settings
from ..database import get_session
from ..models import Certificate, EnrollmentCode, Network, Node, User
from ..services.audit import get_client_ip, log_audit
from ..services.cert_store import read_cert_store_file
from ..services.config_generator import generate_config_for_node, get_dns_client_config
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
    platform: Optional[str] = None  # desktop, ios, android - for converting pre-existing nodes


class NodeResponse(BaseModel):
    id: int
    network_id: int
    hostname: str
    ip_address: Optional[str] = None
    groups: list = []
    is_lighthouse: bool = False
    is_relay: bool = False
    public_endpoint: Optional[str] = None
    lighthouse_options: Optional[dict[str, Any]] = None
    logging_options: Optional[dict[str, Any]] = None
    punchy_options: Optional[dict[str, Any]] = None
    status: str = "pending"
    platform: str = "desktop"
    last_seen: Optional[str] = None
    first_polled_at: Optional[str] = None
    checkin_interval_seconds: Optional[int] = None
    created_at: str

    class Config:
        from_attributes = True


async def _ensure_user_can_access_node(
    user: UserInfo,
    session: AsyncSession,
    node: Node,
) -> None:
    """
    Raise 404 if the current user cannot access the given node.

    Uses get_user_nodes, which respects per-network and per-node permissions.
    """
    node_ids = await get_user_nodes(user, session, network_id=node.network_id)
    if node.id not in node_ids:
        raise HTTPException(status_code=404, detail="Node not found")


@router.get("", response_model=list[NodeResponse])
async def list_nodes(
    network_id: Optional[int] = Query(None),
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """List nodes, optionally filtered by network_id."""
    node_ids = await get_user_nodes(user, session, network_id=network_id, include_limited=False)
    if not node_ids:
        return []

    q = select(Node).where(Node.id.in_(node_ids)).order_by(Node.id)
    result = await session.execute(q)
    nodes = result.scalars().all()
    return [
        NodeResponse(
            id=n.id,
            network_id=n.network_id,
            hostname=n.hostname,
            ip_address=n.ip_address,
            groups=n.groups or [],
            is_lighthouse=n.is_lighthouse,
            is_relay=n.is_relay,
            public_endpoint=n.public_endpoint,
            lighthouse_options=n.lighthouse_options,
            logging_options=n.logging_options,
            punchy_options=n.punchy_options,
            status=n.status,
            platform=n.platform,
            last_seen=n.last_seen.isoformat() if n.last_seen else None,
            first_polled_at=n.first_polled_at.isoformat() if n.first_polled_at else None,
            checkin_interval_seconds=n.checkin_interval_seconds,
            created_at=n.created_at.isoformat() if n.created_at else "",
        )
        for n in nodes
    ]


@router.get("/{node_id}/config")
async def get_node_config(
    node_id: int,
    request: Request,
    enable_dns: bool = Query(False, description="Android only: include a full-override mobile_nebula DNS block"),
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Generate and return Nebula YAML config for this node (with inline PKI when key is stored)."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await _ensure_user_can_access_node(user, session, node)
    if not node.ip_address:
        raise HTTPException(
            status_code=404,
            detail="Node has no certificate. Create a certificate first.",
        )
    result = await session.execute(select(Network).where(Network.id == node.network_id))
    network = result.scalar_one_or_none()
    if not network or not network.ca_cert_path:
        raise HTTPException(status_code=404, detail="Network or CA not found")
    host_cert_path = Path(settings.cert_store_path) / str(node.network_id) / "hosts" / f"{node.hostname}.crt"
    if not host_cert_path.exists():
        raise HTTPException(status_code=404, detail="Host certificate not found")
    host_key_path = Path(settings.cert_store_path) / str(node.network_id) / "hosts" / f"{node.hostname}.key"
    ca_path = Path(network.ca_cert_path)
    if not ca_path.exists():
        raise HTTPException(status_code=404, detail="CA certificate not found")
    ca_content = read_cert_store_file(ca_path)
    host_cert_content = read_cert_store_file(host_cert_path)
    if host_key_path.exists():
        host_key_content = read_cert_store_file(host_key_path)
        inline_pki = (ca_content, host_cert_content, host_key_content)
    else:
        inline_pki = None

    mobile_dns = None
    if node.platform == "ios":
        # Automatic whenever the network has DNS enabled - iOS's matchDomains
        # makes this a genuinely scoped, safe default (see Nodes.tsx/plan notes).
        dns_config = await get_dns_client_config(session, node.network_id)
        if dns_config:
            domain, dns_servers = dns_config
            if dns_servers:
                mobile_dns = {"dns_resolvers": dns_servers, "match_domains": [domain]}
    elif node.platform == "android" and enable_dns:
        # Opt-in only: no domain-scoping on Android, so this is a full DNS
        # override while connected. match_domains=[""] tells the app "all
        # domains" (Mobile Nebula's own convention for a blanket resolver).
        dns_config = await get_dns_client_config(session, node.network_id)
        if dns_config:
            _domain, dns_servers = dns_config
            if dns_servers:
                mobile_dns = {"dns_resolvers": dns_servers, "match_domains": [""]}

    yaml_config = await generate_config_for_node(
        session, node_id, inline_pki=inline_pki, mobile_dns=mobile_dns
    )
    if yaml_config is None:
        raise HTTPException(status_code=404, detail="Node not found")
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    await log_audit(
        session,
        "node_config_downloaded",
        resource_type="node",
        resource_id=node_id,
        actor_user_id=db_user.id if db_user else None,
        actor_identifier=user.email or user.sub,
        client_ip=get_client_ip(request),
    )
    filename = f"{node.hostname}.yaml" if node else "config.yaml"
    return Response(
        content=yaml_config,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{node_id}/certs")
async def get_node_certs(
    node_id: int,
    request: Request,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Return a ZIP with ca.crt, host.crt, and README for this node."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await _ensure_user_can_access_node(user, session, node)
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
    ca_content = read_cert_store_file(ca_path)
    host_cert_content = read_cert_store_file(host_cert_path)
    if host_key_path.exists():
        host_key_content = read_cert_store_file(host_key_path)
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
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    await log_audit(
        session,
        "node_certs_downloaded",
        resource_type="node",
        resource_id=node_id,
        actor_user_id=db_user.id if db_user else None,
        actor_identifier=user.email or user.sub,
        client_ip=get_client_ip(request),
    )
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
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get a single node by ID."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await _ensure_user_can_access_node(user, session, node)
    return NodeResponse(
        id=node.id,
        network_id=node.network_id,
        hostname=node.hostname,
        ip_address=node.ip_address,
        groups=node.groups or [],
        is_lighthouse=node.is_lighthouse,
        is_relay=node.is_relay,
        public_endpoint=node.public_endpoint,
        lighthouse_options=node.lighthouse_options,
        logging_options=node.logging_options,
        punchy_options=node.punchy_options,
        status=node.status,
        platform=node.platform,
        last_seen=node.last_seen.isoformat() if node.last_seen else None,
        first_polled_at=node.first_polled_at.isoformat() if node.first_polled_at else None,
        checkin_interval_seconds=node.checkin_interval_seconds,
        created_at=node.created_at.isoformat() if node.created_at else "",
    )


@router.patch("/{node_id}")
async def update_node(
    node_id: int,
    body: NodeUpdate,
    request: Request,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Update node group (single), lighthouse flag, public endpoint, or lighthouse options."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await _ensure_user_can_access_node(user, session, node)

    original_groups = list(node.groups or [])
    original_is_lighthouse = node.is_lighthouse
    original_is_relay = node.is_relay
    original_public_endpoint = node.public_endpoint
    original_lighthouse_options = (
        node.lighthouse_options.copy()
        if isinstance(node.lighthouse_options, dict)
        else node.lighthouse_options
    )
    original_logging_options = (
        node.logging_options.copy()
        if isinstance(node.logging_options, dict)
        else node.logging_options
    )
    original_punchy_options = (
        node.punchy_options.copy()
        if isinstance(node.punchy_options, dict)
        else node.punchy_options
    )
    original_platform = node.platform
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
    if body.platform is not None:
        platform = body.platform.strip().lower()
        if platform not in ("desktop", "ios", "android"):
            raise HTTPException(status_code=400, detail="platform must be one of: desktop, ios, android")
        if platform != "desktop" and (node.is_lighthouse or node.is_relay):
            raise HTTPException(
                status_code=400,
                detail="Mobile nodes cannot be a lighthouse or relay. Unset those first.",
            )
        node.platform = platform

    await session.flush()

    changed: dict[str, dict[str, Any]] = {}

    new_groups = node.groups or []
    if original_groups != new_groups:
        changed["groups"] = {"old": original_groups, "new": new_groups}

    if original_is_lighthouse != node.is_lighthouse:
        changed["is_lighthouse"] = {
            "old": original_is_lighthouse,
            "new": node.is_lighthouse,
        }

    if original_is_relay != node.is_relay:
        changed["is_relay"] = {"old": original_is_relay, "new": node.is_relay}

    if original_public_endpoint != node.public_endpoint:
        changed["public_endpoint"] = {
            "old": original_public_endpoint,
            "new": node.public_endpoint,
        }

    if original_lighthouse_options != node.lighthouse_options:
        changed["lighthouse_options"] = {
            "old": original_lighthouse_options,
            "new": node.lighthouse_options,
        }

    if original_logging_options != node.logging_options:
        changed["logging_options"] = {
            "old": original_logging_options,
            "new": node.logging_options,
        }

    if original_punchy_options != node.punchy_options:
        changed["punchy_options"] = {
            "old": original_punchy_options,
            "new": node.punchy_options,
        }

    if original_platform != node.platform:
        changed["platform"] = {"old": original_platform, "new": node.platform}

    # A group change alters what's baked into the signed certificate (nebula-cert sign
    # -groups), so re-sign it now rather than leaving the DB and the cert out of sync
    # until someone thinks to re-enroll. Keeps the existing IP and keypair - the running
    # device picks up the new cert on its next config poll, no re-enrollment needed.
    cert_resigned = False
    if "groups" in changed:
        if node.public_key and node.ip_address:
            net_result = await session.execute(select(Network).where(Network.id == node.network_id))
            network = net_result.scalar_one_or_none()
            if not network:
                raise HTTPException(status_code=404, detail="Network not found")
            cert_manager = CertManager(session)
            try:
                await cert_manager.resign_host_certificate(node, network)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            cert_resigned = True
        # else: node has no certificate yet - nothing to resign. The new group will be
        # used whenever a certificate is first issued for it.

    if changed:
        user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
        db_user = user_result.scalar_one_or_none()
        await log_audit(
            session,
            "node_updated",
            resource_type="node",
            resource_id=node_id,
            actor_user_id=db_user.id if db_user else None,
            actor_identifier=user.email or user.sub,
            client_ip=get_client_ip(request),
            details={"changed": changed},
        )
        if cert_resigned:
            await log_audit(
                session,
                "node_cert_resigned",
                resource_type="node",
                resource_id=node_id,
                actor_user_id=db_user.id if db_user else None,
                actor_identifier=user.email or user.sub,
                client_ip=get_client_ip(request),
                details={"reason": "group_changed", "new_groups": new_groups},
            )

    return {"ok": True, "cert_resigned": cert_resigned}


class NodeDeleteRequest(BaseModel):
    reauth_token: str
    confirmation: str  # Must match node hostname


async def _verify_reauth_or_403(user: UserInfo, reauth_token: str, session: AsyncSession) -> None:
    """Shared step-up-auth check for destructive node actions (delete, revoke cert)."""
    reauth_payload = decode_reauth_token(reauth_token)
    if not reauth_payload or reauth_payload.get("sub") != user.sub:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired reauthentication")
    challenge = reauth_payload.get("challenge")
    if not await verify_reauth(user.sub, challenge, session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reauthentication required")


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: int,
    body: NodeDeleteRequest,
    request: Request,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete a node: release IP, remove host cert/key files, delete related records and node.
    Requires reauthentication and typed confirmation of the node's hostname."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await _ensure_user_can_access_node(user, session, node)

    await _verify_reauth_or_403(user, body.reauth_token, session)
    if body.confirmation != node.hostname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirmation does not match node hostname")

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

    # 3. Delete related records (certificates, enrollment_codes)
    await session.execute(delete(Certificate).where(Certificate.node_id == node_id))
    await session.execute(delete(EnrollmentCode).where(EnrollmentCode.node_id == node_id))

    # 4. Delete the node
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    await session.delete(node)
    await session.flush()
    await log_audit(
        session,
        "node_deleted",
        resource_type="node",
        resource_id=node_id,
        actor_user_id=db_user.id if db_user else None,
        actor_identifier=user.email or user.sub,
        client_ip=get_client_ip(request),
    )
    await clear_reauth_challenge(user.sub, session)
    return None


class RevokeCertificateRequest(BaseModel):
    reauth_token: str
    confirmation: str  # Must match node hostname


@router.post("/{node_id}/revoke-certificate")
async def revoke_node_certificate(
    node_id: int,
    body: RevokeCertificateRequest,
    request: Request,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Revoke the node's certificate and take it offline. Node record is kept; can re-enroll later.
    Requires reauthentication and typed confirmation of the node's hostname."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await _ensure_user_can_access_node(user, session, node)

    await _verify_reauth_or_403(user, body.reauth_token, session)
    if body.confirmation != node.hostname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirmation does not match node hostname")

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
    node.status = "revoked"
    await session.flush()
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    await log_audit(
        session,
        "cert_revoked",
        resource_type="node",
        resource_id=node_id,
        actor_user_id=db_user.id if db_user else None,
        actor_identifier=user.email or user.sub,
        client_ip=get_client_ip(request),
    )
    await clear_reauth_challenge(user.sub, session)
    return {"ok": True}


@router.post("/{node_id}/re-enroll")
async def reenroll_node(
    node_id: int,
    request: Request,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Revoke existing certificate (if any) and issue a new one for this node. Returns success; frontend creates enrollment code."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await _ensure_user_can_access_node(user, session, node)

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
        await session.flush()

    # Device is not enrolled until it polls with the new code
    node.first_polled_at = None
    node.last_seen = None
    await session.flush()

    # Load network and create new certificate for existing node
    net_result = await session.execute(select(Network).where(Network.id == node.network_id))
    network = net_result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")

    cert_manager = CertManager(session)
    await cert_manager.create_host_certificate_for_existing_node(node, network)
    await session.flush()
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    await log_audit(
        session,
        "node_reenrolled",
        resource_type="node",
        resource_id=node.id,
        actor_user_id=db_user.id if db_user else None,
        actor_identifier=user.email or user.sub,
        client_ip=get_client_ip(request),
    )
    return {"ok": True, "node_id": node.id}
