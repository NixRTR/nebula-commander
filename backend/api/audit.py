"""Audit log API: system-admin-only read access."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth.oidc import UserInfo
from ..auth.permissions import require_system_admin
from ..database import get_session
from ..models.db import AuditLog, User

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditEntryResponse(BaseModel):
    id: int
    occurred_at: datetime
    action: str
    actor_user_id: Optional[int]
    actor_identifier: Optional[str]
    actor_email: Optional[str]
    resource_type: Optional[str]
    resource_id: Optional[int]
    result: str
    details: Optional[str]
    client_ip: Optional[str]

    class Config:
        from_attributes = True


@router.get("", response_model=list[AuditEntryResponse])
async def list_audit_logs(
    _admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
):
    """List audit log entries (system admins only). Ordered by occurred_at descending."""
    q = select(AuditLog).options(selectinload(AuditLog.actor_user))
    if action is not None:
        q = q.where(AuditLog.action == action)
    if resource_type is not None:
        q = q.where(AuditLog.resource_type == resource_type)
    if from_date is not None:
        q = q.where(AuditLog.occurred_at >= from_date)
    if to_date is not None:
        q = q.where(AuditLog.occurred_at <= to_date)
    q = q.order_by(AuditLog.occurred_at.desc()).offset(offset).limit(limit)
    result = await session.execute(q)
    rows = result.scalars().all()

    return [
        AuditEntryResponse(
            id=row.id,
            occurred_at=row.occurred_at,
            action=row.action,
            actor_user_id=row.actor_user_id,
            actor_identifier=row.actor_identifier,
            actor_email=row.actor_user.email if row.actor_user else None,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            result=row.result,
            details=row.details,
            client_ip=row.client_ip,
        )
        for row in rows
    ]
