"""Networks API: create and list Nebula networks."""
import ipaddress
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo
from ..auth.permissions import (
    check_network_permission,
    check_access_grant,
    get_user_networks,
)
from ..auth.reauth import verify_reauth, clear_reauth_challenge
from ..database import get_session
from ..models import Network, NetworkGroupFirewall, NetworkPermission, NetworkSettings, User
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


class NetworkListResponse(NetworkResponse):
    """List response including current user's permission for the network."""
    role: Optional[str] = None  # owner, member, or admin (for system-admin view)
    can_manage_nodes: Optional[bool] = None
    can_invite_users: Optional[bool] = None
    can_manage_firewall: Optional[bool] = None


class NetworkUpdate(BaseModel):
    """No network-level firewall (defined.net style: only per-group inbound rules)."""
    pass


@router.get("", response_model=list[NetworkListResponse])
async def list_networks(
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    List networks the user has access to.
    Includes current user's role and permission flags per network.
    System admins see all networks (with limited data, role=admin).
    """
    # Get user's database record to check permissions
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        # Create user record if it doesn't exist
        db_user = User(oidc_sub=user.sub, email=user.email, system_role=user.system_role)
        session.add(db_user)
        await session.flush()
        await session.refresh(db_user)
    
    # System admins see all networks (with limited data)
    if user.system_role == "system-admin":
        result = await session.execute(select(Network).order_by(Network.id))
        networks = result.scalars().all()
        return [
            NetworkListResponse(
                id=n.id,
                name=n.name,
                subnet_cidr=n.subnet_cidr,
                ca_cert_path=None,  # Redacted for system admins
                created_at=n.created_at.isoformat() if n.created_at else "",
                role="admin",
                can_manage_nodes=True,
                can_invite_users=True,
                can_manage_firewall=True,
            )
            for n in networks
        ]
    
    # Get networks where user has permission
    network_ids = await get_user_networks(user, session)
    
    if not network_ids:
        return []
    
    result = await session.execute(
        select(Network).where(Network.id.in_(network_ids)).order_by(Network.id)
    )
    networks = result.scalars().all()
    
    # Load user's permission for each network
    perm_result = await session.execute(
        select(NetworkPermission).where(
            NetworkPermission.user_id == db_user.id,
            NetworkPermission.network_id.in_(network_ids),
        )
    )
    perms = {p.network_id: p for p in perm_result.scalars().all()}
    
    return [
        NetworkListResponse(
            id=n.id,
            name=n.name,
            subnet_cidr=n.subnet_cidr,
            ca_cert_path=n.ca_cert_path,
            created_at=n.created_at.isoformat() if n.created_at else "",
            role=perms[n.id].role if n.id in perms else None,
            can_manage_nodes=perms[n.id].can_manage_nodes if n.id in perms else None,
            can_invite_users=perms[n.id].can_invite_users if n.id in perms else None,
            can_manage_firewall=perms[n.id].can_manage_firewall if n.id in perms else None,
        )
        for n in networks
    ]


@router.post("", response_model=NetworkResponse)
async def create_network(
    body: NetworkCreate,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Create a new Nebula network.
    Any authenticated user can create; creator becomes the network owner.
    """
    # Get or create user record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        db_user = User(oidc_sub=user.sub, email=user.email, system_role=user.system_role)
        session.add(db_user)
        await session.flush()
        await session.refresh(db_user)
    
    existing = await session.execute(
        select(Network).where(Network.name == body.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Network with name '{body.name}' already exists",
        )
    
    # Create network
    network = Network(name=body.name, subnet_cidr=body.subnet_cidr)
    session.add(network)
    await session.flush()
    await session.refresh(network)
    
    # Create network permission for creator as owner
    permission = NetworkPermission(
        user_id=db_user.id,
        network_id=network.id,
        role="owner",
        can_manage_nodes=True,
        can_invite_users=True,
        can_manage_firewall=True,
    )
    session.add(permission)
    
    # Create default network settings
    settings = NetworkSettings(
        network_id=network.id,
        auto_approve_nodes=False,
        default_node_groups=[],
        default_is_lighthouse=False,
        default_is_relay=False,
    )
    session.add(settings)
    
    await session.flush()
    
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
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get a single network by ID.
    System admins see limited data unless they have an access grant.
    """
    result = await session.execute(select(Network).where(Network.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        db_user = User(oidc_sub=user.sub, email=user.email, system_role=user.system_role)
        session.add(db_user)
        await session.flush()
        await session.refresh(db_user)
    
    # Check permission
    if user.system_role == "system-admin":
        # Check for access grant
        has_grant = await check_access_grant(db_user.id, "network", network_id, session)
        ca_cert_path = network.ca_cert_path if has_grant else None
    else:
        # Check network permission
        has_permission = await check_network_permission(
            db_user.id, network_id, "owner", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access this network"
            )
        ca_cert_path = network.ca_cert_path
    
    return NetworkResponse(
        id=network.id,
        name=network.name,
        subnet_cidr=network.subnet_cidr,
        ca_cert_path=ca_cert_path,
        created_at=network.created_at.isoformat() if network.created_at else "",
    )


@router.patch("/{network_id}", response_model=NetworkResponse)
async def update_network(
    network_id: int,
    body: NetworkUpdate,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Update network. No network-level firewall (use Groups page for per-group inbound rules).
    Requires network owner permission.
    """
    result = await session.execute(select(Network).where(Network.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Check permission (only owners can update)
    has_permission = await check_network_permission(
        db_user.id, network_id, "owner", session
    )
    if not has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only network owners can update networks"
        )
    
    await session.refresh(network)
    return NetworkResponse(
        id=network.id,
        name=network.name,
        subnet_cidr=network.subnet_cidr,
        ca_cert_path=network.ca_cert_path,
        created_at=network.created_at.isoformat() if network.created_at else "",
    )


class NetworkDeleteRequest(BaseModel):
    reauth_token: str
    confirmation: str  # Must match network name


@router.delete("/{network_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_network(
    network_id: int,
    body: NetworkDeleteRequest,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Delete a network (requires reauthentication and confirmation).
    Only network owners can delete networks.
    """
    result = await session.execute(select(Network).where(Network.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Check permission (only owners can delete; system admins can delete any network)
    if user.system_role != "system-admin":
        has_permission = await check_network_permission(
            db_user.id, network_id, "owner", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only network owners can delete networks"
            )
    
    # Verify reauthentication
    from ..auth.reauth import decode_reauth_token
    reauth_payload = decode_reauth_token(body.reauth_token)
    if not reauth_payload or reauth_payload.get("sub") != user.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired reauthentication"
        )
    
    challenge = reauth_payload.get("challenge")
    if not verify_reauth(user.sub, challenge):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reauthentication required"
        )
    
    # Verify confirmation matches network name
    if body.confirmation != network.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation does not match network name"
        )
    
    # Delete network (cascade will handle related records)
    await session.delete(network)
    await session.flush()
    
    # Clear reauth challenge
    clear_reauth_challenge(user.sub)
    
    return None


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
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """List per-group firewall configs for this network."""
    result = await session.execute(select(Network).where(Network.id == network_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Check permission
    if user.system_role != "system-admin":
        has_permission = await check_network_permission(
            db_user.id, network_id, "manage_firewall", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view firewall rules for this network"
            )
    
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
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Create or update inbound firewall rules for a group in this network (defined.net style)."""
    group_name = (group_name or "").strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="Group name is required")
    result = await session.execute(select(Network).where(Network.id == network_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Check permission
    has_permission = await check_network_permission(
        db_user.id, network_id, "manage_firewall", session
    )
    if not has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to manage firewall rules for this network"
        )
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
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Remove per-group firewall config for this network + group."""
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Check permission
    has_permission = await check_network_permission(
        db_user.id, network_id, "manage_firewall", session
    )
    if not has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to manage firewall rules for this network"
        )
    
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
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Check if an IP is available (not allocated) in this network. Returns 400 if IP is not in the network subnet."""
    result = await session.execute(select(Network).where(Network.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Check permission
    if user.system_role != "system-admin":
        has_permission = await check_network_permission(
            db_user.id, network_id, "manage_nodes", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to check IPs for this network"
            )
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
