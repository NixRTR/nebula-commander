"""Networks API: create and list Nebula networks."""
import ipaddress
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo
from ..database import get_session
from ..models import Network
from ..services.ip_allocator import IPAllocator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/networks", tags=["networks"])


class NetworkCreate(BaseModel):
    name: str
    subnet_cidr: str


class NetworkResponse(BaseModel):
    id: int
    name: str
    subnet_cidr: str
    ca_cert_path: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=list[NetworkResponse])
async def list_networks(
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """List all networks."""
    result = await session.execute(select(Network).order_by(Network.id))
    networks = result.scalars().all()
    return [
        NetworkResponse(
            id=n.id,
            name=n.name,
            subnet_cidr=n.subnet_cidr,
            ca_cert_path=n.ca_cert_path,
            created_at=n.created_at.isoformat() if n.created_at else "",
        )
        for n in networks
    ]


@router.post("", response_model=NetworkResponse)
async def create_network(
    body: NetworkCreate,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a new Nebula network."""
    existing = await session.execute(
        select(Network).where(Network.name == body.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Network with name '{body.name}' already exists",
        )
    network = Network(name=body.name, subnet_cidr=body.subnet_cidr)
    session.add(network)
    await session.flush()
    await session.refresh(network)
    return NetworkResponse(
        id=network.id,
        name=network.name,
        subnet_cidr=network.subnet_cidr,
        ca_cert_path=network.ca_cert_path,
        created_at=network.created_at.isoformat() if network.created_at else "",
    )


@router.get("/{network_id}", response_model=NetworkResponse)
async def get_network(
    network_id: int,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get a single network by ID."""
    result = await session.execute(select(Network).where(Network.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    return NetworkResponse(
        id=network.id,
        name=network.name,
        subnet_cidr=network.subnet_cidr,
        ca_cert_path=network.ca_cert_path,
        created_at=network.created_at.isoformat() if network.created_at else "",
    )


class CheckIpResponse(BaseModel):
    available: bool


@router.get("/{network_id}/check-ip", response_model=CheckIpResponse)
async def check_ip(
    network_id: int,
    ip: str = Query(..., description="IP address to check"),
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Check if an IP is available (not allocated) in this network. Returns 400 if IP is not in the network subnet."""
    result = await session.execute(select(Network).where(Network.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    try:
        net = ipaddress.ip_network(network.subnet_cidr, strict=False)
        addr = ipaddress.ip_address(ip)
        if addr not in net or addr in (net.network_address, net.broadcast_address):
            raise HTTPException(
                status_code=400,
                detail="IP is not a valid host address in this network's subnet.",
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid IP or subnet: {e}")
    ip_allocator = IPAllocator(session)
    allocated = await ip_allocator.is_allocated(network_id, ip)
    return CheckIpResponse(available=not allocated)
