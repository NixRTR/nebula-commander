"""
Permission checking functions for role-based access control.
"""
from datetime import datetime
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models.db import AccessGrant, NetworkPermission, NodePermission, Network, Node
from .oidc import require_user, UserInfo


async def require_system_admin(
    user: Annotated[UserInfo, Depends(require_user)]
) -> UserInfo:
    """Dependency: require system-admin role."""
    if user.system_role != "system-admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System administrator access required"
        )
    return user


async def check_network_permission(
    user_id: int,
    network_id: int,
    permission: str,
    session: AsyncSession,
) -> bool:
    """
    Check if user has specific permission for a network.
    
    Args:
        user_id: User's database ID
        network_id: Network ID
        permission: Permission to check (owner, manage_nodes, invite_users, manage_firewall)
        session: Database session
    
    Returns:
        True if user has permission, False otherwise
    """
    stmt = select(NetworkPermission).where(
        NetworkPermission.user_id == user_id,
        NetworkPermission.network_id == network_id
    )
    result = await session.execute(stmt)
    perm = result.scalar_one_or_none()
    
    if not perm:
        return False
    
    if permission == "owner":
        return perm.role == "owner"
    elif permission in ("manage_nodes", "can_manage_nodes"):
        return perm.role == "owner" or perm.can_manage_nodes
    elif permission in ("invite_users", "can_invite_users"):
        return perm.role == "owner" or perm.can_invite_users
    elif permission in ("manage_firewall", "can_manage_firewall"):
        return perm.role == "owner" or perm.can_manage_firewall
    
    return False


async def check_node_permission(
    user_id: int,
    node_id: int,
    permission: str,
    session: AsyncSession,
) -> bool:
    """
    Check if user has specific permission for a node.
    
    Args:
        user_id: User's database ID
        node_id: Node ID
        permission: Permission to check (view_details, download_config, download_cert)
        session: Database session
    
    Returns:
        True if user has permission, False otherwise
    """
    # First check if user has network-level permission
    stmt = select(Node).where(Node.id == node_id)
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()
    
    if not node:
        return False
    
    # Check network permission (owners have full access)
    has_network_perm = await check_network_permission(
        user_id, node.network_id, "owner", session
    )
    if has_network_perm:
        return True
    
    # Check node-specific permission
    stmt = select(NodePermission).where(
        NodePermission.user_id == user_id,
        NodePermission.node_id == node_id
    )
    result = await session.execute(stmt)
    perm = result.scalar_one_or_none()
    
    if not perm:
        return False
    
    if permission == "view_details":
        return perm.can_view_details
    elif permission == "download_config":
        return perm.can_download_config
    elif permission == "download_cert":
        return perm.can_download_cert
    
    return False


async def check_access_grant(
    admin_user_id: int,
    resource_type: str,
    resource_id: int,
    session: AsyncSession,
) -> bool:
    """
    Check if system admin has temporary access grant to a resource.
    
    Args:
        admin_user_id: Admin user's database ID
        resource_type: Type of resource (network, node)
        resource_id: Resource ID
        session: Database session
    
    Returns:
        True if valid access grant exists, False otherwise
    """
    now = datetime.utcnow()
    stmt = select(AccessGrant).where(
        AccessGrant.admin_user_id == admin_user_id,
        AccessGrant.resource_type == resource_type,
        AccessGrant.resource_id == resource_id,
        AccessGrant.revoked_at.is_(None),
        AccessGrant.expires_at > now
    )
    result = await session.execute(stmt)
    grant = result.scalar_one_or_none()
    
    return grant is not None


async def get_user_networks(
    user: UserInfo,
    session: AsyncSession,
    include_limited: bool = False
) -> list[int]:
    """
    Get list of network IDs the user has access to.
    
    Args:
        user: Current user info
        session: Database session
        include_limited: If True, system admins see all networks (with limited data)
    
    Returns:
        List of network IDs
    """
    from ..models import User
    
    # System admins can see all networks if include_limited is True
    if user.system_role == "system-admin" and include_limited:
        stmt = select(Network.id)
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]
    
    # Get user's database ID from oidc_sub
    db_user = await session.scalar(select(User).where(User.oidc_sub == user.sub))
    if not db_user:
        return []
    
    # Get networks where user has permission
    stmt = select(NetworkPermission.network_id).where(
        NetworkPermission.user_id == db_user.id
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def get_user_nodes(
    user: UserInfo,
    session: AsyncSession,
    network_id: Optional[int] = None,
    include_limited: bool = False
) -> list[int]:
    """
    Get list of node IDs the user has access to.
    
    Args:
        user: Current user info
        session: Database session
        network_id: Optional network ID to filter by
        include_limited: If True, system admins see all nodes (with limited data)
    
    Returns:
        List of node IDs
    """
    from ..models import User
    
    # System admins can see all nodes if include_limited is True
    if user.system_role == "system-admin" and include_limited:
        stmt = select(Node.id)
        if network_id:
            stmt = stmt.where(Node.network_id == network_id)
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]
    
    # Get user's database ID from oidc_sub
    db_user = await session.scalar(select(User).where(User.oidc_sub == user.sub))
    if not db_user:
        return []
    
    # Get nodes from networks where user has permission
    network_ids = await get_user_networks(user, session)
    
    stmt = select(Node.id).where(Node.network_id.in_(network_ids))
    if network_id:
        stmt = stmt.where(Node.network_id == network_id)
    
    result = await session.execute(stmt)
    node_ids = [row[0] for row in result.all()]
    
    # Also include nodes with specific node permissions
    stmt = select(NodePermission.node_id).where(
        NodePermission.user_id == db_user.id
    )
    if network_id:
        # Join with nodes to filter by network
        stmt = stmt.join(Node).where(Node.network_id == network_id)
    
    result = await session.execute(stmt)
    node_ids.extend([row[0] for row in result.all()])
    
    return list(set(node_ids))  # Remove duplicates
