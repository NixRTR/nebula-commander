"""Heartbeat API: nodes report status to update last_seen and status."""
import re
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
    peer_reachability: Optional[dict[int, bool]] = None
    available_subnets: Optional[list[dict]] = None
    os_platform: Optional[str] = None
    client_version: Optional[str] = None
    auto_update: Optional[str] = None
    update_available: Optional[str] = None


_VERSION_RE = re.compile(r"^[0-9A-Za-z.+-]{1,32}$")
_AUTO_UPDATE_MODES = ("off", "install", "notify")


def _clean_version(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    return value if _VERSION_RE.match(value) else None


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

    A lighthouse may also report ping-reachability for other nodes on its network
    (peer_reachability). This is only honored when the reporting node is itself a
    lighthouse (checked server-side, never trusted from the payload) and is scoped to
    nodes on the same network, so a lighthouse can't report on - or spoof - nodes it
    has no relationship to.

    available_subnets and os_platform are self-reported by ncclient (Linux only) so the
    UI can offer subnet-router/exit-node routes to advertise and gate that feature to
    confirmed-Linux nodes (Node.platform alone can't distinguish a Linux desktop from a
    Windows one). Always overwritten wholesale, not merged - a stale interface should
    disappear from what's offered, not linger.
    """
    if token_node_id != node_id:
        raise HTTPException(status_code=403, detail="Token does not match node_id")
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    node.last_seen = datetime.utcnow()
    node.status = "active"
    if body.available_subnets is not None:
        node.available_subnets = body.available_subnets
    if body.os_platform is not None:
        node.os_platform = body.os_platform.strip().lower() or None
    # Client version / auto-update state (read-only on the server). Only clients that
    # know about auto-update send these; update_available: null means "none".
    if "client_version" in body.model_fields_set:
        node.client_version = _clean_version(body.client_version)
    if "auto_update" in body.model_fields_set:
        node.auto_update = body.auto_update if body.auto_update in _AUTO_UPDATE_MODES else None
    if "update_available" in body.model_fields_set:
        node.update_available = _clean_version(body.update_available)
    if body.interval_seconds is not None:
        node.checkin_interval_seconds = max(
            MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, body.interval_seconds)
        )
    if body.peer_reachability and node.is_lighthouse:
        now = datetime.utcnow()
        peers_result = await session.execute(
            select(Node).where(
                Node.network_id == node.network_id,
                Node.id.in_(body.peer_reachability.keys()),
            )
        )
        for peer in peers_result.scalars().all():
            peer.lighthouse_reachable = body.peer_reachability[peer.id]
            peer.lighthouse_checked_at = now
    await session.flush()
    return {"ok": True, "last_seen": node.last_seen.isoformat()}
