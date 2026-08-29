"""Heartbeat API: nodes report status to update last_seen and status."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_device_token
from ..database import get_session
from ..models import Node

router = APIRouter(prefix="/api/nodes", tags=["heartbeat"])

MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 3600


class HeartbeatRequest(BaseModel):
    interval_seconds: Optional[int] = None


@router.post("/{node_id}/heartbeat")
async def node_heartbeat(
    node_id: int,
    body: HeartbeatRequest = HeartbeatRequest(),
    token_node_id: int = Depends(require_device_token),
    session: AsyncSession = Depends(get_session),
):
    """Update node last_seen and set status to active. Called periodically by ncclient using its device token.

    Optionally reports the client's configured check-in interval so the dashboard can
    detect an offline node relative to its actual cadence rather than a guessed default.
    """
    if token_node_id != node_id:
        raise HTTPException(status_code=403, detail="Token does not match node_id")
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    node.last_seen = datetime.utcnow()
    node.status = "active"
    if body.interval_seconds is not None:
        node.checkin_interval_seconds = max(
            MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, body.interval_seconds)
        )
    await session.flush()
    return {"ok": True, "last_seen": node.last_seen.isoformat()}
