"""Invitations API: network owners invite users to join networks."""
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo, get_current_user_optional
from ..auth.permissions import check_network_permission
from ..database import get_session
from ..models import Invitation, User, Network, NetworkPermission
from ..services.email import send_invitation_email
from ..config import settings

router = APIRouter(prefix="/api/invitations", tags=["invitations"])


class InvitationCreate(BaseModel):
    email: EmailStr
    network_id: int
    role: str = "member"  # owner, member
    can_manage_nodes: bool = False
    can_invite_users: bool = False
    can_manage_firewall: bool = False
    expires_in_days: int = 7


class InvitationResponse(BaseModel):
    id: int
    email: str
    network_id: int
    network_name: str
    invited_by_user_id: int
    invited_by_email: Optional[str]
    token: str
    role: str
    can_manage_nodes: bool
    can_invite_users: bool
    can_manage_firewall: bool
    status: str
    expires_at: str
    accepted_at: Optional[str] = None
    created_at: str
    email_status: str
    email_sent_at: Optional[str] = None
    email_error: Optional[str] = None

    class Config:
        from_attributes = True


class InvitationPublicResponse(BaseModel):
    """Public invitation details (no token)."""
    email: str
    network_name: str
    invited_by_email: Optional[str]
    role: str
    can_manage_nodes: bool
    can_invite_users: bool
    can_manage_firewall: bool
    status: str
    expires_at: str


@router.post("", response_model=InvitationResponse)
async def create_invitation(
    body: InvitationCreate,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Create an invitation to join a network.
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
    
    # Check if user has permission to invite users to this network
    if user.system_role != "system-admin":
        has_permission = await check_network_permission(
            db_user.id, body.network_id, "can_invite_users", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to invite users to this network"
            )
    
    # Get network
    network_result = await session.execute(select(Network).where(Network.id == body.network_id))
    network = network_result.scalar_one_or_none()
    
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Check if user is already a member of this network
    existing_perm = await session.execute(
        select(NetworkPermission).join(
            User, NetworkPermission.user_id == User.id
        ).where(
            User.email == body.email,
            NetworkPermission.network_id == body.network_id
        )
    )
    if existing_perm.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="User is already a member of this network"
        )
    
    # Check if there's already a pending invitation
    existing_invitation = await session.execute(
        select(Invitation).where(
            Invitation.email == body.email,
            Invitation.network_id == body.network_id,
            Invitation.status == "pending"
        )
    )
    if existing_invitation.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="There is already a pending invitation for this user to this network"
        )
    
    # Generate unique token
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=body.expires_in_days)
    
    # Create invitation
    invitation = Invitation(
        email=body.email,
        network_id=body.network_id,
        invited_by_user_id=db_user.id,
        token=token,
        role=body.role,
        can_manage_nodes=body.can_manage_nodes,
        can_invite_users=body.can_invite_users,
        can_manage_firewall=body.can_manage_firewall,
        status="pending",
        expires_at=expires_at,
        email_status="sending" if settings.smtp_enabled else "not_sent",
    )
    session.add(invitation)
    await session.flush()
    await session.refresh(invitation)
    
    # Queue email sending as background task
    if settings.smtp_enabled:
        # Determine base URL for invitation link from env (oidc_redirect_uri or public_url)
        if settings.oidc_redirect_uri:
            base_url = settings.oidc_redirect_uri.rsplit('/api/auth/callback', 1)[0] if '/api/auth/callback' in settings.oidc_redirect_uri else settings.oidc_redirect_uri.rsplit('/auth/callback', 1)[0]
        elif settings.public_url:
            base_url = settings.public_url.rstrip("/")
        else:
            base_url = "http://localhost:9090"
        
        background_tasks.add_task(
            send_invitation_email,
            invitation_id=invitation.id,
            to_email=invitation.email,
            network_name=network.name,
            invited_by_email=db_user.email or "Unknown",
            invitation_token=invitation.token,
            role=invitation.role,
            permissions={
                "can_manage_nodes": invitation.can_manage_nodes,
                "can_invite_users": invitation.can_invite_users,
                "can_manage_firewall": invitation.can_manage_firewall,
            },
            expires_at=invitation.expires_at.strftime("%B %d, %Y"),
            base_url=base_url,
        )
    
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        network_id=invitation.network_id,
        network_name=network.name,
        invited_by_user_id=invitation.invited_by_user_id,
        invited_by_email=db_user.email,
        token=invitation.token,
        role=invitation.role,
        can_manage_nodes=invitation.can_manage_nodes,
        can_invite_users=invitation.can_invite_users,
        can_manage_firewall=invitation.can_manage_firewall,
        status=invitation.status,
        expires_at=invitation.expires_at.isoformat() if invitation.expires_at else "",
        accepted_at=invitation.accepted_at.isoformat() if invitation.accepted_at else None,
        created_at=invitation.created_at.isoformat() if invitation.created_at else "",
        email_status=invitation.email_status,
        email_sent_at=invitation.email_sent_at.isoformat() if invitation.email_sent_at else None,
        email_error=invitation.email_error,
    )


@router.get("", response_model=list[InvitationResponse])
async def list_invitations(
    network_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    List invitations.
    Network owners see invitations for their networks.
    System admins see all invitations.
    """
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        return []
    
    # Build query
    stmt = select(Invitation)
    
    # Filter by network ownership (unless system admin)
    if user.system_role != "system-admin":
        # Get networks where user can invite users
        perms_result = await session.execute(
            select(NetworkPermission.network_id).where(
                NetworkPermission.user_id == db_user.id,
                or_(
                    NetworkPermission.role == "owner",
                    NetworkPermission.can_invite_users == True
                )
            )
        )
        network_ids = [row[0] for row in perms_result.fetchall()]
        
        if not network_ids:
            return []
        
        stmt = stmt.where(Invitation.network_id.in_(network_ids))
    
    # Filter by network_id if provided
    if network_id is not None:
        stmt = stmt.where(Invitation.network_id == network_id)
    
    # Filter by status if provided
    if status_filter:
        stmt = stmt.where(Invitation.status == status_filter)
    
    stmt = stmt.order_by(Invitation.created_at.desc())
    
    result = await session.execute(stmt)
    invitations = result.scalars().all()
    
    responses = []
    for invitation in invitations:
        # Get network
        network_result = await session.execute(select(Network).where(Network.id == invitation.network_id))
        network = network_result.scalar_one_or_none()
        
        # Get inviter
        inviter_result = await session.execute(select(User).where(User.id == invitation.invited_by_user_id))
        inviter = inviter_result.scalar_one_or_none()
        
        responses.append(InvitationResponse(
            id=invitation.id,
            email=invitation.email,
            network_id=invitation.network_id,
            network_name=network.name if network else "Unknown",
            invited_by_user_id=invitation.invited_by_user_id,
            invited_by_email=inviter.email if inviter else None,
            token=invitation.token,
            role=invitation.role,
            can_manage_nodes=invitation.can_manage_nodes,
            can_invite_users=invitation.can_invite_users,
            can_manage_firewall=invitation.can_manage_firewall,
            status=invitation.status,
            email_status=invitation.email_status,
            email_sent_at=invitation.email_sent_at.isoformat() if invitation.email_sent_at else None,
            email_error=invitation.email_error,
            expires_at=invitation.expires_at.isoformat() if invitation.expires_at else "",
            accepted_at=invitation.accepted_at.isoformat() if invitation.accepted_at else None,
            created_at=invitation.created_at.isoformat() if invitation.created_at else "",
        ))
    
    return responses


@router.get("/public/{token}", response_model=InvitationPublicResponse)
async def get_invitation_public(
    token: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Get invitation details by token (public endpoint, no auth required).
    Used to display invitation details before accepting.
    """
    # Get invitation
    result = await session.execute(select(Invitation).where(Invitation.token == token))
    invitation = result.scalar_one_or_none()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    # Check if expired
    if invitation.expires_at < datetime.utcnow():
        if invitation.status == "pending":
            invitation.status = "expired"
            await session.flush()
        raise HTTPException(status_code=410, detail="Invitation has expired")
    
    # Check if already accepted or revoked
    if invitation.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Invitation is {invitation.status}"
        )
    
    # Get network
    network_result = await session.execute(select(Network).where(Network.id == invitation.network_id))
    network = network_result.scalar_one_or_none()
    
    # Get inviter
    inviter_result = await session.execute(select(User).where(User.id == invitation.invited_by_user_id))
    inviter = inviter_result.scalar_one_or_none()
    
    return InvitationPublicResponse(
        email=invitation.email,
        network_name=network.name if network else "Unknown",
        invited_by_email=inviter.email if inviter else None,
        role=invitation.role,
        can_manage_nodes=invitation.can_manage_nodes,
        can_invite_users=invitation.can_invite_users,
        can_manage_firewall=invitation.can_manage_firewall,
        status=invitation.status,
        expires_at=invitation.expires_at.isoformat() if invitation.expires_at else "",
    )


@router.post("/{token}/accept", status_code=status.HTTP_200_OK)
async def accept_invitation(
    token: str,
    user_info: Optional[UserInfo] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_session),
):
    """
    Accept an invitation.
    Creates NetworkPermission for the user.
    User must be authenticated.
    """
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="You must be logged in to accept an invitation"
        )
    
    # Get invitation
    result = await session.execute(select(Invitation).where(Invitation.token == token))
    invitation = result.scalar_one_or_none()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    # Check if expired
    if invitation.expires_at < datetime.utcnow():
        if invitation.status == "pending":
            invitation.status = "expired"
            await session.flush()
        raise HTTPException(status_code=410, detail="Invitation has expired")
    
    # Check if already accepted or revoked
    if invitation.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Invitation is {invitation.status}"
        )
    
    # Get or create user
    user_result = await session.execute(select(User).where(User.oidc_sub == user_info.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        # Create user if doesn't exist
        db_user = User(
            oidc_sub=user_info.sub,
            email=user_info.email,
            system_role=user_info.system_role,
        )
        session.add(db_user)
        await session.flush()
        await session.refresh(db_user)
    
    # Verify email matches (optional check)
    if db_user.email and invitation.email.lower() != db_user.email.lower():
        raise HTTPException(
            status_code=400,
            detail="This invitation is for a different email address"
        )
    
    # Check if user is already a member
    existing_perm = await session.execute(
        select(NetworkPermission).where(
            NetworkPermission.user_id == db_user.id,
            NetworkPermission.network_id == invitation.network_id
        )
    )
    if existing_perm.scalar_one_or_none():
        # Mark as accepted anyway
        invitation.status = "accepted"
        invitation.accepted_at = datetime.utcnow()
        await session.flush()
        return {"message": "You are already a member of this network"}
    
    # Create network permission
    permission = NetworkPermission(
        user_id=db_user.id,
        network_id=invitation.network_id,
        role=invitation.role,
        can_manage_nodes=invitation.can_manage_nodes,
        can_invite_users=invitation.can_invite_users,
        can_manage_firewall=invitation.can_manage_firewall,
        invited_by_user_id=invitation.invited_by_user_id,
    )
    session.add(permission)
    
    # Mark invitation as accepted
    invitation.status = "accepted"
    invitation.accepted_at = datetime.utcnow()
    
    await session.flush()
    
    return {"message": "Invitation accepted successfully"}


@router.post("/{invitation_id}/resend", response_model=InvitationResponse)
async def resend_invitation_email(
    invitation_id: int,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Resend invitation email."""
    # Get invitation
    invitation = await session.get(Invitation, invitation_id)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    # Check permissions (must be network owner or system admin)
    network = await session.get(Network, invitation.network_id)
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Get user details
    db_user = await session.scalar(select(User).where(User.oidc_sub == user.sub))
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Permission check
    if user.system_role != "system-admin":
        has_permission = await check_network_permission(
            db_user.id, network.id, "invite_users", session
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to manage invitations for this network"
            )
    
    # Check if invitation is still pending
    if invitation.status != "pending":
        raise HTTPException(status_code=400, detail="Can only resend pending invitations")
    
    # Update status to sending if SMTP is enabled
    if settings.smtp_enabled:
        invitation.email_status = "sending"
        await session.flush()
    
    # Queue email
    if settings.smtp_enabled:
        # Determine base URL for invitation link from env (oidc_redirect_uri or public_url)
        if settings.oidc_redirect_uri:
            base_url = settings.oidc_redirect_uri.rsplit('/api/auth/callback', 1)[0] if '/api/auth/callback' in settings.oidc_redirect_uri else settings.oidc_redirect_uri.rsplit('/auth/callback', 1)[0]
        elif settings.public_url:
            base_url = settings.public_url.rstrip("/")
        else:
            base_url = "http://localhost:9090"
        
        background_tasks.add_task(
            send_invitation_email,
            invitation_id=invitation.id,
            to_email=invitation.email,
            network_name=network.name,
            invited_by_email=db_user.email or "Unknown",
            invitation_token=invitation.token,
            role=invitation.role,
            permissions={
                "can_manage_nodes": invitation.can_manage_nodes,
                "can_invite_users": invitation.can_invite_users,
                "can_manage_firewall": invitation.can_manage_firewall,
            },
            expires_at=invitation.expires_at.strftime("%B %d, %Y"),
            base_url=base_url,
        )
    
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        network_id=invitation.network_id,
        network_name=network.name,
        invited_by_user_id=invitation.invited_by_user_id,
        invited_by_email=db_user.email,
        token=invitation.token,
        role=invitation.role,
        can_manage_nodes=invitation.can_manage_nodes,
        can_invite_users=invitation.can_invite_users,
        can_manage_firewall=invitation.can_manage_firewall,
        status=invitation.status,
        email_status=invitation.email_status,
        email_sent_at=invitation.email_sent_at.isoformat() if invitation.email_sent_at else None,
        email_error=invitation.email_error,
        expires_at=invitation.expires_at.isoformat(),
        accepted_at=invitation.accepted_at.isoformat() if invitation.accepted_at else None,
        created_at=invitation.created_at.isoformat(),
    )


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: int,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Revoke an invitation.
    Only the inviter or network owners can revoke.
    """
    # Get user's database record
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Get invitation
    invitation_result = await session.execute(select(Invitation).where(Invitation.id == invitation_id))
    invitation = invitation_result.scalar_one_or_none()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    # Check permission (inviter, network owner, or system admin)
    if user.system_role != "system-admin":
        if invitation.invited_by_user_id != db_user.id:
            # Check if user is network owner
            has_permission = await check_network_permission(
                db_user.id, invitation.network_id, "owner", session
            )
            if not has_permission:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the inviter or network owners can revoke this invitation"
                )
    
    # Revoke invitation
    invitation.status = "revoked"
    await session.flush()
    
    return None
