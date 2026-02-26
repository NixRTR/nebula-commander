"""Node Requests API: request/approve workflow for node creation."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo
from ..auth.permissions import check_network_permission
from ..database import get_session
from ..models import NodeRequest, Network, User, NetworkPermission, NetworkSettings, Node
from ..services.audit import get_client_ip, log_audit

router = APIRouter(prefix="/api/node-requests", tags=["node-requests"])


class NodeRequestCreate(BaseModel):
    network_id: int
    hostname: str
    groups: List[str] = []
    is_lighthouse: bool = False
    is_relay: bool = False


class NodeRequestResponse(BaseModel):
    id: int
    network_id: int
    network_name: str
    requested_by_user_id: int
    requested_by_email: Optional[str]
    hostname: str
    groups: List[str]
    is_lighthouse: bool
    is_relay: bool
    status: str
    created_at: str
    processed_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_node_id: Optional[int] = None

    class Config:
        from_attributes = True


@router.post("", response_model=NodeRequestResponse)
async def create_node_request(
    body: NodeRequestCreate,
    request: Request,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Create a node request.
    If network has auto-approve enabled for this user, node is created immediately.
    """
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        db_user = User(oidc_sub=user.sub, email=user.email, system_role=user.system_role)
        session.add(db_user)
        await session.flush()
        await session.refresh(db_user)
    
    # Check if network exists
    network_result = await session.execute(select(Network).where(Network.id == body.network_id))
    network = network_result.scalar_one_or_none()
    
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Check if user has permission to request nodes for this network
    has_permission = await check_network_permission(
        db_user.id, body.network_id, "manage_nodes", session
    )
    
    # Check network settings for auto-approve
    settings_result = await session.execute(
        select(NetworkSettings).where(NetworkSettings.network_id == body.network_id)
    )
    network_settings = settings_result.scalar_one_or_none()
    
    auto_approve = False
    if has_permission:
        # Users with manage_nodes permission can create nodes directly
        auto_approve = True
    elif network_settings and network_settings.auto_approve_nodes:
        auto_approve = True
    
    # Create node request
    node_request = NodeRequest(
        network_id=body.network_id,
        requested_by_user_id=db_user.id,
        hostname=body.hostname,
        groups=body.groups,
        is_lighthouse=body.is_lighthouse,
        is_relay=body.is_relay,
        status="approved" if auto_approve else "pending",
        processed_at=datetime.utcnow() if auto_approve else None,
        approved_by_user_id=db_user.id if auto_approve else None,
    )
    session.add(node_request)
    await session.flush()
    await session.refresh(node_request)
    
    # If auto-approved, create the node
    if auto_approve:
        # Import here to avoid circular dependency
        from ..services.ip_allocator import IPAllocator
        
        ip_allocator = IPAllocator(session)
        ip_address = await ip_allocator.allocate_next(body.network_id)
        
        node = Node(
            network_id=body.network_id,
            hostname=body.hostname,
            ip_address=ip_address,
            groups=body.groups,
            is_lighthouse=body.is_lighthouse,
            is_relay=body.is_relay,
            status="pending",
        )
        session.add(node)
        await session.flush()
        await session.refresh(node)
        
        node_request.created_node_id = node.id
        await session.flush()
        await log_audit(
            session,
            "node_request_approved",
            resource_type="node_request",
            resource_id=node_request.id,
            actor_user_id=db_user.id,
            actor_identifier=db_user.email or user.sub,
            client_ip=get_client_ip(request),
            details={"created_node_id": node.id},
        )
    else:
        await log_audit(
            session,
            "node_request_created",
            resource_type="node_request",
            resource_id=node_request.id,
            actor_user_id=db_user.id,
            actor_identifier=db_user.email or user.sub,
            client_ip=get_client_ip(request),
        )
    
    return NodeRequestResponse(
        id=node_request.id,
        network_id=node_request.network_id,
        network_name=network.name,
        requested_by_user_id=node_request.requested_by_user_id,
        requested_by_email=db_user.email,
        hostname=node_request.hostname,
        groups=node_request.groups or [],
        is_lighthouse=node_request.is_lighthouse,
        is_relay=node_request.is_relay,
        status=node_request.status,
        created_at=node_request.created_at.isoformat() if node_request.created_at else "",
        processed_at=node_request.processed_at.isoformat() if node_request.processed_at else None,
        rejection_reason=node_request.rejection_reason,
        created_node_id=node_request.created_node_id,
    )


@router.get("", response_model=list[NodeRequestResponse])
async def list_node_requests(
    network_id: Optional[int] = None,
    status: Optional[str] = None,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    List node requests.
    Users see their own requests.
    Network owners see requests for their networks.
    System admins see all requests.
    """
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        return []
    
    # Build query
    stmt = select(NodeRequest)
    
    if user.system_role == "system-admin":
        # System admins see all requests
        pass
    else:
        # Get networks where user is owner or has manage_nodes permission
        network_perms = await session.execute(
            select(NetworkPermission).where(
                NetworkPermission.user_id == db_user.id,
                or_(
                    NetworkPermission.role == "owner",
                    NetworkPermission.can_manage_nodes == True
                )
            )
        )
        managed_network_ids = [p.network_id for p in network_perms.scalars().all()]
        
        # Filter to user's own requests or requests for networks they manage
        stmt = stmt.where(
            or_(
                NodeRequest.requested_by_user_id == db_user.id,
                NodeRequest.network_id.in_(managed_network_ids)
            )
        )
    
    if network_id:
        stmt = stmt.where(NodeRequest.network_id == network_id)
    
    if status:
        stmt = stmt.where(NodeRequest.status == status)
    
    stmt = stmt.order_by(NodeRequest.created_at.desc())
    
    result = await session.execute(stmt)
    requests = result.scalars().all()
    
    responses = []
    for req in requests:
        # Get network name
        network_result = await session.execute(select(Network).where(Network.id == req.network_id))
        network = network_result.scalar_one_or_none()
        
        # Get requester email
        requester_result = await session.execute(select(User).where(User.id == req.requested_by_user_id))
        requester = requester_result.scalar_one_or_none()
        
        responses.append(NodeRequestResponse(
            id=req.id,
            network_id=req.network_id,
            network_name=network.name if network else "Unknown",
            requested_by_user_id=req.requested_by_user_id,
            requested_by_email=requester.email if requester else None,
            hostname=req.hostname,
            groups=req.groups or [],
            is_lighthouse=req.is_lighthouse,
            is_relay=req.is_relay,
            status=req.status,
            created_at=req.created_at.isoformat() if req.created_at else "",
            processed_at=req.processed_at.isoformat() if req.processed_at else None,
            rejection_reason=req.rejection_reason,
            created_node_id=req.created_node_id,
        ))
    
    return responses


class ApproveNodeRequestRequest(BaseModel):
    pass


@router.post("/{request_id}/approve", response_model=NodeRequestResponse)
async def approve_node_request(
    request_id: int,
    body: ApproveNodeRequestRequest,
    request: Request,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Approve a node request and create the node."""
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Get node request
    request_result = await session.execute(select(NodeRequest).where(NodeRequest.id == request_id))
    node_request = request_result.scalar_one_or_none()
    
    if not node_request:
        raise HTTPException(status_code=404, detail="Node request not found")
    
    if node_request.status != "pending":
        raise HTTPException(status_code=400, detail="Request is not pending")
    
    # Check permission
    has_permission = await check_network_permission(
        db_user.id, node_request.network_id, "manage_nodes", session
    )
    
    if not has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to approve nodes for this network"
        )
    
    # Create the node
    from ..services.ip_allocator import IPAllocator
    
    ip_allocator = IPAllocator(session)
    ip_address = await ip_allocator.allocate_next(node_request.network_id)
    
    node = Node(
        network_id=node_request.network_id,
        hostname=node_request.hostname,
        ip_address=ip_address,
        groups=node_request.groups,
        is_lighthouse=node_request.is_lighthouse,
        is_relay=node_request.is_relay,
        status="pending",
    )
    session.add(node)
    await session.flush()
    await session.refresh(node)
    
    # Update request
    node_request.status = "approved"
    node_request.approved_by_user_id = db_user.id
    node_request.processed_at = datetime.utcnow()
    node_request.created_node_id = node.id
    await session.flush()
    await log_audit(
        session,
        "node_request_approved",
        resource_type="node_request",
        resource_id=request_id,
        actor_user_id=db_user.id,
        actor_identifier=db_user.email or user.sub,
        client_ip=get_client_ip(request),
        details={"created_node_id": node.id},
    )
    
    # Get network name
    network_result = await session.execute(select(Network).where(Network.id == node_request.network_id))
    network = network_result.scalar_one_or_none()
    
    # Get requester email
    requester_result = await session.execute(select(User).where(User.id == node_request.requested_by_user_id))
    requester = requester_result.scalar_one_or_none()
    
    return NodeRequestResponse(
        id=node_request.id,
        network_id=node_request.network_id,
        network_name=network.name if network else "Unknown",
        requested_by_user_id=node_request.requested_by_user_id,
        requested_by_email=requester.email if requester else None,
        hostname=node_request.hostname,
        groups=node_request.groups or [],
        is_lighthouse=node_request.is_lighthouse,
        is_relay=node_request.is_relay,
        status=node_request.status,
        created_at=node_request.created_at.isoformat() if node_request.created_at else "",
        processed_at=node_request.processed_at.isoformat() if node_request.processed_at else None,
        rejection_reason=node_request.rejection_reason,
        created_node_id=node_request.created_node_id,
    )


class RejectNodeRequestRequest(BaseModel):
    reason: str


@router.post("/{request_id}/reject", response_model=NodeRequestResponse)
async def reject_node_request(
    request_id: int,
    body: RejectNodeRequestRequest,
    request: Request,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Reject a node request."""
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Get node request
    request_result = await session.execute(select(NodeRequest).where(NodeRequest.id == request_id))
    node_request = request_result.scalar_one_or_none()
    
    if not node_request:
        raise HTTPException(status_code=404, detail="Node request not found")
    
    if node_request.status != "pending":
        raise HTTPException(status_code=400, detail="Request is not pending")
    
    # Check permission
    has_permission = await check_network_permission(
        db_user.id, node_request.network_id, "manage_nodes", session
    )
    
    if not has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to reject nodes for this network"
        )
    
    # Update request
    node_request.status = "rejected"
    node_request.approved_by_user_id = db_user.id
    node_request.processed_at = datetime.utcnow()
    node_request.rejection_reason = body.reason
    await session.flush()
    await log_audit(
        session,
        "node_request_rejected",
        resource_type="node_request",
        resource_id=request_id,
        actor_user_id=db_user.id,
        actor_identifier=db_user.email or user.sub,
        client_ip=get_client_ip(request),
        details={"reason": body.reason},
    )
    
    # Get network name
    network_result = await session.execute(select(Network).where(Network.id == node_request.network_id))
    network = network_result.scalar_one_or_none()
    
    # Get requester email
    requester_result = await session.execute(select(User).where(User.id == node_request.requested_by_user_id))
    requester = requester_result.scalar_one_or_none()
    
    return NodeRequestResponse(
        id=node_request.id,
        network_id=node_request.network_id,
        network_name=network.name if network else "Unknown",
        requested_by_user_id=node_request.requested_by_user_id,
        requested_by_email=requester.email if requester else None,
        hostname=node_request.hostname,
        groups=node_request.groups or [],
        is_lighthouse=node_request.is_lighthouse,
        is_relay=node_request.is_relay,
        status=node_request.status,
        created_at=node_request.created_at.isoformat() if node_request.created_at else "",
        processed_at=node_request.processed_at.isoformat() if node_request.processed_at else None,
        rejection_reason=node_request.rejection_reason,
        created_node_id=node_request.created_node_id,
    )
