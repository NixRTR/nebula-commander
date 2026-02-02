"""Certificates API: create (server-generated keypair), sign (betterkeys), list."""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.oidc import require_user, UserInfo
from ..config import settings
from ..database import get_session
from pathlib import Path
from ..models import Network, Node, Certificate
from ..services.cert_manager import CertManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/certificates", tags=["certificates"])


class SignRequest(BaseModel):
    """Request to sign a host cert (betterkeys: client sends public key)."""

    network_id: int
    name: str
    public_key: str
    groups: Optional[list[str]] = None
    suggested_ip: Optional[str] = None
    duration_days: Optional[int] = None


class SignResponse(BaseModel):
    ip_address: str
    certificate: str
    ca_certificate: Optional[str] = None


class CreateRequest(BaseModel):
    """Request to create a certificate (server generates keypair)."""

    network_id: int
    name: str
    groups: Optional[list[str]] = None
    suggested_ip: Optional[str] = None
    duration_days: Optional[int] = None


class CreateResponse(BaseModel):
    ip_address: str
    certificate: str
    private_key: str
    ca_certificate: Optional[str] = None


class CertificateListItem(BaseModel):
    id: int
    node_id: int
    node_name: str
    network_id: int
    network_name: str
    ip_address: Optional[str]
    issued_at: datetime
    expires_at: datetime
    revoked_at: Optional[datetime] = None


@router.post("/sign", response_model=SignResponse)
async def sign_certificate(
    body: SignRequest,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Sign a host certificate. Client must send the public key (betterkeys).
    Returns assigned IP and signed certificate PEM.
    """
    result = await session.execute(
        select(Network).where(Network.id == body.network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")

    cert_manager = CertManager(session)
    duration = body.duration_days or settings.default_cert_expiry_days
    ip, cert_pem = await cert_manager.sign_host(
        network=network,
        name=body.name,
        public_key_pem=body.public_key,
        groups=body.groups,
        suggested_ip=body.suggested_ip,
        duration_days=duration,
    )

    # Create or update node and certificate record
    node_result = await session.execute(
        select(Node).where(
            Node.network_id == body.network_id,
            Node.hostname == body.name,
        )
    )
    node = node_result.scalar_one_or_none()
    if not node:
        node = Node(
            network_id=body.network_id,
            hostname=body.name,
            public_key=body.public_key,
            ip_address=ip,
            status="active",
            groups=body.groups or [],
        )
        session.add(node)
        await session.flush()
    else:
        node.ip_address = ip
        node.public_key = body.public_key
        node.groups = body.groups or node.groups
        node.status = "active"
        await session.flush()

    expires_at = datetime.utcnow() + timedelta(days=duration)
    cert_record = Certificate(
        node_id=node.id,
        expires_at=expires_at,
        cert_path=None,
    )
    session.add(cert_record)
    await session.flush()

    ca_pem = None
    if network.ca_cert_path:
        try:
            ca_pem = Path(network.ca_cert_path).read_text()
        except Exception:
            pass

    return SignResponse(
        ip_address=ip,
        certificate=cert_pem,
        ca_certificate=ca_pem,
    )


@router.post("/create", response_model=CreateResponse)
async def create_certificate(
    body: CreateRequest,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Create a host certificate. Server generates the keypair, signs it, and returns
    the private key, signed cert, and CA cert. The private key is returned only once;
    copy it to your node securely.
    """
    result = await session.execute(
        select(Network).where(Network.id == body.network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")

    cert_manager = CertManager(session)
    duration = body.duration_days or settings.default_cert_expiry_days
    ip, cert_pem, private_key_pem, ca_pem, public_key_pem = await cert_manager.create_host_certificate(
        network=network,
        name=body.name,
        groups=body.groups,
        suggested_ip=body.suggested_ip,
        duration_days=duration,
    )

    # Create or update node and certificate record (do not store private key)
    node_result = await session.execute(
        select(Node).where(
            Node.network_id == body.network_id,
            Node.hostname == body.name,
        )
    )
    node = node_result.scalar_one_or_none()
    if not node:
        node = Node(
            network_id=body.network_id,
            hostname=body.name,
            public_key=public_key_pem,
            ip_address=ip,
            status="active",
            groups=body.groups or [],
        )
        session.add(node)
        await session.flush()
    else:
        node.ip_address = ip
        node.public_key = public_key_pem
        node.groups = body.groups or node.groups
        node.status = "active"
        await session.flush()

    expires_at = datetime.utcnow() + timedelta(days=duration)
    cert_record = Certificate(
        node_id=node.id,
        expires_at=expires_at,
        cert_path=None,
    )
    session.add(cert_record)
    await session.flush()

    return CreateResponse(
        ip_address=ip,
        certificate=cert_pem,
        private_key=private_key_pem,
        ca_certificate=ca_pem or None,
    )


@router.get("", response_model=list[CertificateListItem])
async def list_certificates(
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    network_id: Optional[int] = Query(None, description="Filter by network"),
):
    """List issued certificates, optionally filtered by network."""
    stmt = (
        select(Certificate, Node, Network)
        .join(Node, Certificate.node_id == Node.id)
        .join(Network, Node.network_id == Network.id)
    )
    if network_id is not None:
        stmt = stmt.where(Network.id == network_id)
    stmt = stmt.order_by(Certificate.issued_at.desc())
    result = await session.execute(stmt)
    rows = result.all()
    return [
        CertificateListItem(
            id=c.id,
            node_id=n.id,
            node_name=n.hostname,
            network_id=net.id,
            network_name=net.name,
            ip_address=n.ip_address,
            issued_at=c.issued_at,
            expires_at=c.expires_at,
            revoked_at=c.revoked_at,
        )
        for c, n, net in rows
    ]
