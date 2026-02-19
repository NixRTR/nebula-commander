"""Users API: system admin user management."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import UserInfo
from ..auth.permissions import require_system_admin
from ..database import get_session
from ..models import User, NetworkPermission

router = APIRouter(prefix="/api/users", tags=["users"])


class UserResponse(BaseModel):
    id: int
    oidc_sub: str
    email: Optional[str]
    system_role: str
    created_at: str
    network_count: int = 0

    class Config:
        from_attributes = True


class UserDetailResponse(UserResponse):
    networks: List[dict] = []


@router.get("", response_model=list[UserResponse])
async def list_users(
    _admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    """List all users (system admins only)."""
    result = await session.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    
    responses = []
    for user in users:
        # Count networks (server-side for performance)
        network_count = await session.scalar(
            select(func.count()).select_from(NetworkPermission).where(
                NetworkPermission.user_id == user.id
            )
        ) or 0
        
        responses.append(UserResponse(
            id=user.id,
            oidc_sub=user.oidc_sub,
            email=user.email,
            system_role=user.system_role,
            created_at=user.created_at.isoformat() if user.created_at else "",
            network_count=network_count,
        ))
    
    return responses


@router.get("/{user_id}", response_model=UserDetailResponse)
async def get_user(
    user_id: int,
    _admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    """Get user details (system admins only)."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get user's networks
    network_result = await session.execute(
        select(NetworkPermission).where(NetworkPermission.user_id == user_id)
    )
    permissions = network_result.scalars().all()
    
    networks = []
    for perm in permissions:
        from ..models import Network
        net_result = await session.execute(select(Network).where(Network.id == perm.network_id))
        network = net_result.scalar_one_or_none()
        if network:
            networks.append({
                "id": network.id,
                "name": network.name,
                "role": perm.role,
                "can_manage_nodes": perm.can_manage_nodes,
                "can_invite_users": perm.can_invite_users,
                "can_manage_firewall": perm.can_manage_firewall,
            })
    
    return UserDetailResponse(
        id=user.id,
        oidc_sub=user.oidc_sub,
        email=user.email,
        system_role=user.system_role,
        created_at=user.created_at.isoformat() if user.created_at else "",
        network_count=len(networks),
        networks=networks,
    )


class UserUpdateRequest(BaseModel):
    system_role: Optional[str] = None


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: UserUpdateRequest,
    _admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    """Update user (system admins only)."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if body.system_role:
        if body.system_role not in ("system-admin", "network-owner", "user"):
            raise HTTPException(
                status_code=400,
                detail="Invalid system_role. Must be: system-admin, network-owner, or user"
            )
        user.system_role = body.system_role
    
    await session.flush()
    await session.refresh(user)
    
    # Count networks (server-side for performance)
    network_count = await session.scalar(
        select(func.count()).select_from(NetworkPermission).where(
            NetworkPermission.user_id == user.id
        )
    ) or 0
    
    return UserResponse(
        id=user.id,
        oidc_sub=user.oidc_sub,
        email=user.email,
        system_role=user.system_role,
        created_at=user.created_at.isoformat() if user.created_at else "",
        network_count=network_count,
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    _admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    """Delete user (system admins only). This will remove all their permissions."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    await session.delete(user)
    await session.flush()
    
    return None
