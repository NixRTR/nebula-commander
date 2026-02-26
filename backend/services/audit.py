"""
Audit logging for sensitive actions. Entries are visible to system admins only.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db import AuditLog


def get_client_ip(request: Request) -> str:
    """Get client IP from request, honoring X-Forwarded-For when behind a proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


async def log_audit(
    session: AsyncSession,
    action: str,
    *,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    result: str = "success",
    actor_user_id: Optional[int] = None,
    actor_identifier: Optional[str] = None,
    details: Optional[str] | Optional[dict] = None,
    client_ip: Optional[str] = None,
) -> None:
    """
    Append one audit log entry. Does not commit; caller must commit the session.
    """
    details_str: Optional[str] = None
    if details is not None:
        details_str = json.dumps(details) if isinstance(details, dict) else details

    entry = AuditLog(
        action=action,
        actor_user_id=actor_user_id,
        actor_identifier=actor_identifier,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        details=details_str,
        client_ip=client_ip,
    )
    session.add(entry)
