"""Heartbeat API: nodes report status to update last_seen and status."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, UserInfo
from ..database import get_session
from ..models import Node

router = APIRouter(prefix="/api/nodes", tags=["heartbeat"])


@router.post("/{node_id}/heartbeat")
async def node_heartbeat(
    node_id: int,
    _user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Update node last_seen and set status to active. Call periodically from Nebula nodes."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    node.last_seen = datetime.utcnow()
    node.status = "active"
    await session.flush()
    return {"ok": True, "last_seen": node.last_seen.isoformat()}
