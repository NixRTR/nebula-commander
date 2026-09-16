"""Users API: system admin user management, plus self-service user preferences."""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import UserInfo, require_user
from ..auth.permissions import require_system_admin
from ..auth.reauth import clear_reauth_challenge, decode_reauth_token, verify_reauth
from ..database import get_session
from ..models import (
    User,
    SavedTheme,
    NetworkPermission,
    NodePermission,
    AccessGrant,
    Invitation,
    AuditLog,
)
from ..services.audit import get_client_ip, log_audit
from ..theme_defaults import ALLOWED_TOKEN_KEYS, DEFAULT_THEME

router = APIRouter(prefix="/api/users", tags=["users"])

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeTokenValue(BaseModel):
    light: str
    dark: str


class ThemeResponse(BaseModel):
    theme: dict[str, ThemeTokenValue]


class ThemeUpdateRequest(BaseModel):
    theme: dict[str, ThemeTokenValue]


def _validate_theme_tokens(tokens: dict[str, ThemeTokenValue]) -> None:
    """Shared by update_my_theme and create_my_saved_theme: every key must be a
    known token, every color a plain #rrggbb hex string (no alpha - keeps every
    token editable with a plain <input type="color">)."""
    for key, value in tokens.items():
        if key not in ALLOWED_TOKEN_KEYS:
            raise HTTPException(status_code=400, detail=f"Unknown theme token: {key!r}")
        if not _HEX_COLOR_RE.match(value.light) or not _HEX_COLOR_RE.match(value.dark):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid color for {key!r}: must be a #rrggbb hex string",
            )


@router.get("/me/theme", response_model=ThemeResponse)
async def get_my_theme(
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Return the current user's color theme: their saved overrides merged over
    the built-in defaults, so a client always gets a complete token set."""
    db_user = await session.scalar(select(User).where(User.oidc_sub == user.sub))
    overrides = db_user.theme if db_user and db_user.theme else {}
    merged = {**DEFAULT_THEME, **overrides}
    return ThemeResponse(theme=merged)


@router.put("/me/theme", response_model=ThemeResponse)
async def update_my_theme(
    body: ThemeUpdateRequest,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Merge the given tokens into the current user's saved theme overrides (a
    partial update - tokens not included are left as whatever they already were).
    Each key must be a known token; each color must be a plain #rrggbb hex string
    (no alpha - keeps every token editable with a plain <input type="color">)."""
    _validate_theme_tokens(body.theme)

    db_user = await session.scalar(select(User).where(User.oidc_sub == user.sub))
    if not db_user:
        db_user = User(oidc_sub=user.sub, email=user.email, system_role=user.system_role)
        session.add(db_user)
        await session.flush()

    existing = dict(db_user.theme) if db_user.theme else {}
    existing.update({k: v.model_dump() for k, v in body.theme.items()})
    db_user.theme = existing
    await session.flush()

    return ThemeResponse(theme={**DEFAULT_THEME, **existing})


class SavedThemeCreate(BaseModel):
    name: str
    tokens: dict[str, ThemeTokenValue]


class SavedThemeResponse(BaseModel):
    id: int
    name: str
    tokens: dict[str, ThemeTokenValue]
    created_at: str

    class Config:
        from_attributes = True


@router.get("/me/themes", response_model=list[SavedThemeResponse])
async def list_my_saved_themes(
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """List the current user's saved theme presets (a private, per-account
    library - full token sets included since this is a small personal list)."""
    db_user = await session.scalar(select(User).where(User.oidc_sub == user.sub))
    if not db_user:
        return []
    result = await session.execute(
        select(SavedTheme).where(SavedTheme.user_id == db_user.id).order_by(SavedTheme.created_at)
    )
    return [
        SavedThemeResponse(
            id=st.id, name=st.name, tokens=st.tokens, created_at=st.created_at.isoformat()
        )
        for st in result.scalars().all()
    ]


@router.post("/me/themes", response_model=SavedThemeResponse, status_code=status.HTTP_201_CREATED)
async def create_my_saved_theme(
    body: SavedThemeCreate,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Save the given token set as a new named preset. No "apply" endpoint
    exists - applying a saved theme is just PUT /me/theme with its `tokens`,
    since a saved snapshot always has every token key."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Name must be 100 characters or fewer")
    _validate_theme_tokens(body.tokens)

    db_user = await session.scalar(select(User).where(User.oidc_sub == user.sub))
    if not db_user:
        db_user = User(oidc_sub=user.sub, email=user.email, system_role=user.system_role)
        session.add(db_user)
        await session.flush()

    existing = await session.scalar(
        select(SavedTheme).where(SavedTheme.user_id == db_user.id, SavedTheme.name == name)
    )
    if existing:
        raise HTTPException(status_code=400, detail="A saved theme with this name already exists")

    saved = SavedTheme(
        user_id=db_user.id, name=name, tokens={k: v.model_dump() for k, v in body.tokens.items()}
    )
    session.add(saved)
    await session.flush()

    return SavedThemeResponse(
        id=saved.id, name=saved.name, tokens=saved.tokens, created_at=saved.created_at.isoformat()
    )


@router.delete("/me/themes/{theme_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_saved_theme(
    theme_id: int,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete one of the current user's saved theme presets. Ownership is
    checked (not just id) so one user can't delete another's by guessing an id."""
    db_user = await session.scalar(select(User).where(User.oidc_sub == user.sub))
    saved = None
    if db_user:
        saved = await session.scalar(
            select(SavedTheme).where(SavedTheme.id == theme_id, SavedTheme.user_id == db_user.id)
        )
    if not saved:
        raise HTTPException(status_code=404, detail="Saved theme not found")

    await session.delete(saved)
    await session.flush()
    return None


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
    result = await session.execute(
        select(User).where(User.is_placeholder.is_(False)).order_by(User.created_at.desc())
    )
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
    request: Request,
    admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    """Update user (system admins only)."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if body.system_role:
        if body.system_role not in ("system-admin", "user"):
            raise HTTPException(
                status_code=400,
                detail="Invalid system_role. Must be: system-admin or user"
            )
        user.system_role = body.system_role
    
    await session.flush()
    await session.refresh(user)
    admin_db = await session.scalar(select(User).where(User.oidc_sub == admin.sub))
    await log_audit(
        session,
        "user_role_updated",
        resource_type="user",
        resource_id=user_id,
        actor_user_id=admin_db.id if admin_db else None,
        actor_identifier=admin.email or admin.sub,
        client_ip=get_client_ip(request),
        details={"system_role": user.system_role},
    )
    
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


class UserDeleteRequest(BaseModel):
    reauth_token: str
    confirmation: str  # Must match user's email (or oidc_sub if no email)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    body: UserDeleteRequest,
    request: Request,
    admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    """Delete user (system admins only). This will remove all their permissions.
    Requires reauthentication and typed confirmation of the user's email."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_placeholder:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete the system placeholder user")

    reauth_payload = decode_reauth_token(body.reauth_token)
    if not reauth_payload or reauth_payload.get("sub") != admin.sub:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired reauthentication")
    if not await verify_reauth(admin.sub, reauth_payload.get("challenge"), session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reauthentication required")

    expected_confirmation = user.email or user.oidc_sub
    if body.confirmation != expected_confirmation:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirmation does not match user's email")

    # Attribution ("who did this") columns aren't the user's own data - redirect
    # them to the reserved placeholder (NOT NULL columns) or null them out
    # (nullable columns) instead of leaving them dangling, so the delete below
    # satisfies PRAGMA foreign_keys=ON. Permission/access-grant rows *owned by*
    # this user are handled by ORM cascade on session.delete() (Network/Node
    # permissions, AccessGrant.admin_user).
    sentinel = await session.scalar(select(User).where(User.is_placeholder.is_(True)))
    if sentinel is not None:
        await session.execute(
            update(Invitation).where(Invitation.invited_by_user_id == user.id).values(invited_by_user_id=sentinel.id)
        )
        await session.execute(
            update(AccessGrant).where(AccessGrant.granted_by_user_id == user.id).values(granted_by_user_id=sentinel.id)
        )
    await session.execute(
        update(NetworkPermission).where(NetworkPermission.invited_by_user_id == user.id).values(invited_by_user_id=None)
    )
    await session.execute(
        update(NodePermission).where(NodePermission.granted_by_user_id == user.id).values(granted_by_user_id=None)
    )
    await session.execute(
        update(AuditLog).where(AuditLog.actor_user_id == user.id).values(actor_user_id=None)
    )
    # SavedTheme rows are the user's own data (not attribution), so delete them
    # outright rather than redirecting to the sentinel - no ORM cascade is
    # configured for this table.
    await session.execute(delete(SavedTheme).where(SavedTheme.user_id == user.id))

    await session.delete(user)
    await session.flush()
    admin_db = await session.scalar(select(User).where(User.oidc_sub == admin.sub))
    await log_audit(
        session,
        "user_deleted",
        resource_type="user",
        resource_id=user_id,
        actor_user_id=admin_db.id if admin_db else None,
        actor_identifier=admin.email or admin.sub,
        client_ip=get_client_ip(request),
    )
    await clear_reauth_challenge(admin.sub, session)

    return None
