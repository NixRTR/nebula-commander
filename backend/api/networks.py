"""Networks API: create and list Nebula networks."""
import ipaddress
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo
from ..database import get_session
from ..models import Network, NetworkGroupFirewall
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


class NetworkUpdate(BaseModel):
    """No network-level firewall (defined.net style: only per-group inbound rules)."""
    pass


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


@router.patch("/{network_id}", response_model=NetworkResponse)
async def update_network(
    network_id: int,
    body: NetworkUpdate,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Update network. No network-level firewall (use Groups page for per-group inbound rules)."""
    result = await session.execute(select(Network).where(Network.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    await session.refresh(network)
    return NetworkResponse(
        id=network.id,
        name=network.name,
        subnet_cidr=network.subnet_cidr,
        ca_cert_path=network.ca_cert_path,
        created_at=network.created_at.isoformat() if network.created_at else "",
    )


# Defined.net-style: only inbound rules per group. Rule shape: allowed_group, protocol, port_range, description.
VALID_INBOUND_PROTOS = ("any", "tcp", "udp", "icmp")


def _validate_inbound_rule(rule: dict) -> None:
    """Rule must have allowed_group, protocol, port_range. description optional."""
    if not isinstance(rule, dict):
        raise HTTPException(status_code=400, detail="Each rule must be an object")
    allowed_group = rule.get("allowed_group")
    if not allowed_group or not str(allowed_group).strip():
        raise HTTPException(status_code=400, detail="Each rule must have non-empty 'allowed_group'")
    proto = (rule.get("protocol") or "any").strip().lower()
    if proto not in VALID_INBOUND_PROTOS:
        raise HTTPException(
            status_code=400,
            detail=f"protocol must be one of {VALID_INBOUND_PROTOS}",
        )
    port_range = rule.get("port_range")
    if port_range is None or (isinstance(port_range, str) and not port_range.strip()):
        raise HTTPException(status_code=400, detail="Each rule must have 'port_range' (e.g. 'any' or '22,80-88')")


class GroupFirewallResponse(BaseModel):
    group_name: str
    inbound_rules: List[dict]


class GroupFirewallUpdate(BaseModel):
    inbound_rules: List[dict]


@router.get("/{network_id}/group-firewall", response_model=list[GroupFirewallResponse])
async def list_group_firewall(
    network_id: int,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """List per-group firewall configs for this network."""
    result = await session.execute(select(Network).where(Network.id == network_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Network not found")
    result = await session.execute(
        select(NetworkGroupFirewall).where(NetworkGroupFirewall.network_id == network_id)
    )
    rows = result.scalars().all()
    return [
        GroupFirewallResponse(
            group_name=gf.group_name,
            inbound_rules=gf.inbound_rules or [],
        )
        for gf in rows
    ]


@router.put("/{network_id}/group-firewall/{group_name}", response_model=GroupFirewallResponse)
async def update_group_firewall(
    network_id: int,
    group_name: str,
    body: GroupFirewallUpdate,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Create or update inbound firewall rules for a group in this network (defined.net style)."""
    group_name = (group_name or "").strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="Group name is required")
    result = await session.execute(select(Network).where(Network.id == network_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Network not found")
    for r in body.inbound_rules:
        _validate_inbound_rule(r)
    result = await session.execute(
        select(NetworkGroupFirewall).where(
            NetworkGroupFirewall.network_id == network_id,
            NetworkGroupFirewall.group_name == group_name,
        )
    )
    gf = result.scalar_one_or_none()
    if gf:
        gf.inbound_rules = body.inbound_rules
        gf.outbound_rules = []  # not used; keep column for DB compat
    else:
        gf = NetworkGroupFirewall(
            network_id=network_id,
            group_name=group_name,
            outbound_rules=[],
            inbound_rules=body.inbound_rules,
        )
        session.add(gf)
    await session.flush()
    await session.refresh(gf)
    return GroupFirewallResponse(
        group_name=gf.group_name,
        inbound_rules=gf.inbound_rules or [],
    )


@router.delete("/{network_id}/group-firewall/{group_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_firewall(
    network_id: int,
    group_name: str,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Remove per-group firewall config for this network + group."""
    result = await session.execute(
        select(NetworkGroupFirewall).where(
            NetworkGroupFirewall.network_id == network_id,
            NetworkGroupFirewall.group_name == group_name,
        )
    )
    gf = result.scalar_one_or_none()
    if gf:
        await session.delete(gf)
        await session.flush()
    return None


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
