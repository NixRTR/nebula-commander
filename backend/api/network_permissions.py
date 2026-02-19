"""Network Permissions API: manage users and their permissions within networks."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo
from ..auth.permissions import check_network_permission
from ..database import get_session
from ..models import NetworkPermission, User, Network

router = APIRouter(prefix="/api/networks", tags=["network-permissions"])


class NetworkUserResponse(BaseModel):
    user_id: int
    email: Optional[str]
    role: str
    can_manage_nodes: bool
    can_invite_users: bool
    can_manage_firewall: bool
    invited_by_user_id: Optional[int]
    invited_by_email: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class NetworkUserAddRequest(BaseModel):
    user_id: int
    role: str = "member"
    can_manage_nodes: bool = False
    can_invite_users: bool = False
    can_manage_firewall: bool = False


class NetworkUserUpdateRequest(BaseModel):
    role: Optional[str] = None
    can_manage_nodes: Optional[bool] = None
    can_invite_users: Optional[bool] = None
    can_manage_firewall: Optional[bool] = None


@router.get("/{network_id}/users", response_model=list[NetworkUserResponse])
async def list_network_users(
    network_id: int,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    List users with access to a network.
    Requires network owner permission or system admin.
    """
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Check if network exists
    network_result = await session.execute(select(Network).where(Network.id == network_id))
    network = network_result.scalar_one_or_none()
    
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Check permission (network owner or system admin)
    if user.system_role != "system-admin":
        has_permission = await check_network_permission(
            db_user.id, network_id, "owner", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only network owners can view network users"
            )
    
    # Get all permissions for this network
    result = await session.execute(
        select(NetworkPermission).where(NetworkPermission.network_id == network_id)
    )
    permissions = result.scalars().all()
    
    responses = []
    for perm in permissions:
        # Get user
        perm_user_result = await session.execute(select(User).where(User.id == perm.user_id))
        perm_user = perm_user_result.scalar_one_or_none()
        
        # Get inviter if exists
        inviter = None
        if perm.invited_by_user_id:
            inviter_result = await session.execute(select(User).where(User.id == perm.invited_by_user_id))
            inviter = inviter_result.scalar_one_or_none()
        
        responses.append(NetworkUserResponse(
            user_id=perm.user_id,
            email=perm_user.email if perm_user else None,
            role=perm.role,
            can_manage_nodes=perm.can_manage_nodes,
            can_invite_users=perm.can_invite_users,
            can_manage_firewall=perm.can_manage_firewall,
            invited_by_user_id=perm.invited_by_user_id,
            invited_by_email=inviter.email if inviter else None,
            created_at=perm.created_at.isoformat() if perm.created_at else "",
        ))
    
    return responses


@router.post("/{network_id}/users", response_model=NetworkUserResponse)
async def add_user_to_network(
    network_id: int,
    body: NetworkUserAddRequest,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Add an existing user to a network.
    Requires network owner with can_invite_users permission.
    """
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Validate role
    if body.role not in ("owner", "member"):
        raise HTTPException(status_code=400, detail="Invalid role. Must be: owner or member")
    
    # Check if network exists
    network_result = await session.execute(select(Network).where(Network.id == network_id))
    network = network_result.scalar_one_or_none()
    
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Check permission (network owner with can_invite_users or system admin)
    if user.system_role != "system-admin":
        has_permission = await check_network_permission(
            db_user.id, network_id, "can_invite_users", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to add users to this network"
            )
    
    # Check if target user exists
    target_user_result = await session.execute(select(User).where(User.id == body.user_id))
    target_user = target_user_result.scalar_one_or_none()
    
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")
    
    # Check if user is already a member
    existing_perm = await session.execute(
        select(NetworkPermission).where(
            NetworkPermission.user_id == body.user_id,
            NetworkPermission.network_id == network_id
        )
    )
    if existing_perm.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="User is already a member of this network"
        )
    
    # Create permission
    permission = NetworkPermission(
        user_id=body.user_id,
        network_id=network_id,
        role=body.role,
        can_manage_nodes=body.can_manage_nodes,
        can_invite_users=body.can_invite_users,
        can_manage_firewall=body.can_manage_firewall,
        invited_by_user_id=db_user.id,
    )
    session.add(permission)
    await session.flush()
    await session.refresh(permission)
    
    return NetworkUserResponse(
        user_id=permission.user_id,
        email=target_user.email,
        role=permission.role,
        can_manage_nodes=permission.can_manage_nodes,
        can_invite_users=permission.can_invite_users,
        can_manage_firewall=permission.can_manage_firewall,
        invited_by_user_id=permission.invited_by_user_id,
        invited_by_email=db_user.email,
        created_at=permission.created_at.isoformat() if permission.created_at else "",
    )


@router.patch("/{network_id}/users/{target_user_id}", response_model=NetworkUserResponse)
async def update_network_user(
    network_id: int,
    target_user_id: int,
    body: NetworkUserUpdateRequest,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Update a user's permissions for a network.
    Requires network owner permission.
    """
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Validate role if provided
    if body.role and body.role not in ("owner", "member"):
        raise HTTPException(status_code=400, detail="Invalid role. Must be: owner or member")
    
    # Check if network exists
    network_result = await session.execute(select(Network).where(Network.id == network_id))
    network = network_result.scalar_one_or_none()
    
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Check permission (network owner or system admin)
    if user.system_role != "system-admin":
        has_permission = await check_network_permission(
            db_user.id, network_id, "owner", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only network owners can update user permissions"
            )
    
    # Get permission
    perm_result = await session.execute(
        select(NetworkPermission).where(
            NetworkPermission.user_id == target_user_id,
            NetworkPermission.network_id == network_id
        )
    )
    permission = perm_result.scalar_one_or_none()
    
    if not permission:
        raise HTTPException(status_code=404, detail="User is not a member of this network")
    
    # Prevent removing the last owner
    if body.role and body.role != "owner" and permission.role == "owner":
        # Count owners (server-side for performance)
        owners_count = await session.scalar(
            select(func.count()).select_from(NetworkPermission).where(
                NetworkPermission.network_id == network_id,
                NetworkPermission.role == "owner"
            )
        )
        
        if owners_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last owner from a network"
            )
    
    # Update permission
    if body.role is not None:
        permission.role = body.role
    if body.can_manage_nodes is not None:
        permission.can_manage_nodes = body.can_manage_nodes
    if body.can_invite_users is not None:
        permission.can_invite_users = body.can_invite_users
    if body.can_manage_firewall is not None:
        permission.can_manage_firewall = body.can_manage_firewall
    
    await session.flush()
    await session.refresh(permission)
    
    # Get target user
    target_user_result = await session.execute(select(User).where(User.id == target_user_id))
    target_user = target_user_result.scalar_one_or_none()
    
    # Get inviter if exists
    inviter = None
    if permission.invited_by_user_id:
        inviter_result = await session.execute(select(User).where(User.id == permission.invited_by_user_id))
        inviter = inviter_result.scalar_one_or_none()
    
    return NetworkUserResponse(
        user_id=permission.user_id,
        email=target_user.email if target_user else None,
        role=permission.role,
        can_manage_nodes=permission.can_manage_nodes,
        can_invite_users=permission.can_invite_users,
        can_manage_firewall=permission.can_manage_firewall,
        invited_by_user_id=permission.invited_by_user_id,
        invited_by_email=inviter.email if inviter else None,
        created_at=permission.created_at.isoformat() if permission.created_at else "",
    )


@router.delete("/{network_id}/users/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_from_network(
    network_id: int,
    target_user_id: int,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Remove a user from a network.
    Requires network owner permission.
    Cannot remove the last owner.
    """
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Check if network exists
    network_result = await session.execute(select(Network).where(Network.id == network_id))
    network = network_result.scalar_one_or_none()
    
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Check permission (network owner or system admin)
    if user.system_role != "system-admin":
        has_permission = await check_network_permission(
            db_user.id, network_id, "owner", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only network owners can remove users from the network"
            )
    
    # Get permission
    perm_result = await session.execute(
        select(NetworkPermission).where(
            NetworkPermission.user_id == target_user_id,
            NetworkPermission.network_id == network_id
        )
    )
    permission = perm_result.scalar_one_or_none()
    
    if not permission:
        raise HTTPException(status_code=404, detail="User is not a member of this network")
    
    # Prevent removing the last owner
    if permission.role == "owner":
        # Count owners (server-side for performance)
        owners_count = await session.scalar(
            select(func.count()).select_from(NetworkPermission).where(
                NetworkPermission.network_id == network_id,
                NetworkPermission.role == "owner"
            )
        )
        
        if owners_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last owner from a network"
            )
    
    # Delete permission
    await session.delete(permission)
    await session.flush()
    
    return None
