"""Access Grants API: temporary system admin access to resources."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo
from ..auth.permissions import check_network_permission, require_system_admin
from ..database import get_session
from ..models import AccessGrant, User, Network, Node

router = APIRouter(prefix="/api/access-grants", tags=["access-grants"])


class AccessGrantCreate(BaseModel):
    admin_user_id: int
    resource_type: str  # network, node
    resource_id: int
    duration_hours: int = 24
    reason: str


class AccessGrantResponse(BaseModel):
    id: int
    admin_user_id: int
    admin_email: Optional[str]
    resource_type: str
    resource_id: int
    resource_name: str
    granted_by_user_id: int
    granted_by_email: Optional[str]
    expires_at: str
    created_at: str
    revoked_at: Optional[str] = None
    reason: Optional[str]

    class Config:
        from_attributes = True


@router.post("", response_model=AccessGrantResponse)
async def create_access_grant(
    body: AccessGrantCreate,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Grant temporary access to a system admin for a resource.
    Only network owners can grant access to their resources.
    """
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Get admin user
    admin_result = await session.execute(select(User).where(User.id == body.admin_user_id))
    admin_user = admin_result.scalar_one_or_none()
    
    if not admin_user:
        raise HTTPException(status_code=404, detail="Admin user not found")
    
    if admin_user.system_role != "system-admin":
        raise HTTPException(status_code=400, detail="User is not a system admin")
    
    # Validate resource type
    if body.resource_type not in ("network", "node"):
        raise HTTPException(status_code=400, detail="Invalid resource type")
    
    # Check permission based on resource type
    if body.resource_type == "network":
        # Check if user is network owner
        has_permission = await check_network_permission(
            db_user.id, body.resource_id, "owner", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only network owners can grant access to networks"
            )
        
        # Get network name
        network_result = await session.execute(select(Network).where(Network.id == body.resource_id))
        resource = network_result.scalar_one_or_none()
        if not resource:
            raise HTTPException(status_code=404, detail="Network not found")
        resource_name = resource.name
        
    elif body.resource_type == "node":
        # Get node and check network permission
        node_result = await session.execute(select(Node).where(Node.id == body.resource_id))
        node = node_result.scalar_one_or_none()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        
        has_permission = await check_network_permission(
            db_user.id, node.network_id, "owner", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only network owners can grant access to nodes"
            )
        resource_name = node.hostname
    
    # Create access grant
    expires_at = datetime.utcnow() + timedelta(hours=body.duration_hours)
    
    grant = AccessGrant(
        admin_user_id=body.admin_user_id,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        granted_by_user_id=db_user.id,
        expires_at=expires_at,
        reason=body.reason,
    )
    session.add(grant)
    await session.flush()
    await session.refresh(grant)
    
    return AccessGrantResponse(
        id=grant.id,
        admin_user_id=grant.admin_user_id,
        admin_email=admin_user.email,
        resource_type=grant.resource_type,
        resource_id=grant.resource_id,
        resource_name=resource_name,
        granted_by_user_id=grant.granted_by_user_id,
        granted_by_email=db_user.email,
        expires_at=grant.expires_at.isoformat() if grant.expires_at else "",
        created_at=grant.created_at.isoformat() if grant.created_at else "",
        revoked_at=grant.revoked_at.isoformat() if grant.revoked_at else None,
        reason=grant.reason,
    )


@router.get("", response_model=list[AccessGrantResponse])
async def list_access_grants(
    active_only: bool = True,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    List access grants.
    Network owners see grants they've created.
    System admins see grants for them.
    """
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        return []
    
    # Build query
    stmt = select(AccessGrant)
    
    if user.system_role == "system-admin":
        # System admins see grants for them
        stmt = stmt.where(AccessGrant.admin_user_id == db_user.id)
    else:
        # Network owners see grants they've created
        stmt = stmt.where(AccessGrant.granted_by_user_id == db_user.id)
    
    if active_only:
        now = datetime.utcnow()
        stmt = stmt.where(
            AccessGrant.revoked_at.is_(None),
            AccessGrant.expires_at > now
        )
    
    stmt = stmt.order_by(AccessGrant.created_at.desc())
    
    result = await session.execute(stmt)
    grants = result.scalars().all()
    
    responses = []
    for grant in grants:
        # Get admin user
        admin_result = await session.execute(select(User).where(User.id == grant.admin_user_id))
        admin_user = admin_result.scalar_one_or_none()
        
        # Get granter user
        granter_result = await session.execute(select(User).where(User.id == grant.granted_by_user_id))
        granter_user = granter_result.scalar_one_or_none()
        
        # Get resource name
        if grant.resource_type == "network":
            resource_result = await session.execute(select(Network).where(Network.id == grant.resource_id))
            resource = resource_result.scalar_one_or_none()
            resource_name = resource.name if resource else "Unknown"
        else:
            resource_result = await session.execute(select(Node).where(Node.id == grant.resource_id))
            resource = resource_result.scalar_one_or_none()
            resource_name = resource.hostname if resource else "Unknown"
        
        responses.append(AccessGrantResponse(
            id=grant.id,
            admin_user_id=grant.admin_user_id,
            admin_email=admin_user.email if admin_user else None,
            resource_type=grant.resource_type,
            resource_id=grant.resource_id,
            resource_name=resource_name,
            granted_by_user_id=grant.granted_by_user_id,
            granted_by_email=granter_user.email if granter_user else None,
            expires_at=grant.expires_at.isoformat() if grant.expires_at else "",
            created_at=grant.created_at.isoformat() if grant.created_at else "",
            revoked_at=grant.revoked_at.isoformat() if grant.revoked_at else None,
            reason=grant.reason,
        ))
    
    return responses


@router.delete("/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_access_grant(
    grant_id: int,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Revoke an access grant. Only the granter can revoke."""
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Get grant
    grant_result = await session.execute(select(AccessGrant).where(AccessGrant.id == grant_id))
    grant = grant_result.scalar_one_or_none()
    
    if not grant:
        raise HTTPException(status_code=404, detail="Access grant not found")
    
    # Check permission (only granter can revoke)
    if grant.granted_by_user_id != db_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the granter can revoke this access"
        )
    
    # Revoke grant
    grant.revoked_at = datetime.utcnow()
    await session.flush()
    
    return None
