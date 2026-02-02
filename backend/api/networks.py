"""Networks API: create and list Nebula networks."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo
from ..database import get_session
from ..models import Network

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
