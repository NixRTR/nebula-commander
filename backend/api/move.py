"""
Server move: point every device of this instance at another Nebula Commander server
(after a Backup & export import there), without touching the devices.

The admin pastes the new server's fingerprint (GET /api/instance/fingerprint there,
shown on its Move page) into this one and starts the move with a step-up reauth and a
two-factor code. This instance then signs a move statement with its key
(backend/services/instance_identity.py), hands it to devices on every device response
(backend/middleware/move.py) and goes read-only. ncclient 0.9.0+ waits, checks the new
server against the fingerprint and switches; see client/server_move.py.
"""
import ipaddress
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import mfa
from ..auth.oidc import UserInfo
from ..auth.permissions import require_system_admin
from ..auth.reauth import require_reauth
from ..config import settings
from ..database import get_session
from ..middleware import move as move_middleware
from ..models import InstanceMove, Network, Node, User
from ..services import instance_identity
from ..services.audit import get_client_ip, log_audit

router = APIRouter(prefix="/api/admin/move", tags=["move"])
instance_router = APIRouter(prefix="/api/instance", tags=["move"])

MAX_WAIT_HOURS = 72
DEFAULT_WAIT_HOURS = 24
# ncclient's own minimum wait for a move to another domain or an IP (client/server_move.py)
CLIENT_FOREIGN_FLOOR_HOURS = 24
# First ncclient release that follows moves
MOVE_CLIENT_VERSION = "0.9.0"

_SECOND_LEVEL = ("co", "com", "org", "net", "ac", "gov", "edu")


def registrable_domain(host: str) -> Optional[str]:
    """nebulacdr.net for beardedtek.nebulacdr.net; example.co.uk for nc.example.co.uk;
    None for an IP. Same heuristic as client/server_move.py."""
    host = (host or "").strip().rstrip(".").lower()
    try:
        ipaddress.ip_address(host.strip("[]"))
        return None
    except ValueError:
        pass
    labels = [x for x in host.split(".") if x]
    if len(labels) < 2:
        return host or None
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _own_url(request: Request) -> str:
    return (settings.public_url or str(request.base_url)).rstrip("/")


def _normalize_url(value: str) -> str:
    v = (value or "").strip().rstrip("/")
    if v and "://" not in v:
        v = "https://" + v
    return v


@instance_router.get("/fingerprint")
async def instance_fingerprint(request: Request, session: AsyncSession = Depends(get_session)):
    """This instance's key fingerprint - what an admin pastes into the server they are
    moving away from. Public: it identifies, it doesn't authorize."""
    key = await instance_identity.public_key(session)
    return {"fingerprint": instance_identity.fingerprint(key), "public_key": key, "public_url": _own_url(request)}


def _move_view(move: InstanceMove) -> dict:
    return {
        "move_id": move.move_id,
        "new_url": move.new_url,
        "new_key_fp": move.new_key_fp,
        "wait_hours": move.wait_hours,
        "keep_days": move.keep_days,
        "created_at": move.created_at.isoformat() + "Z",
        "switch_at": move.switch_at.isoformat() + "Z",
        "expires_at": move.expires_at.isoformat() + "Z",
        "recommended_until": (move.switch_at + timedelta(days=move.keep_days)).isoformat() + "Z",
        "status": move.status,
    }


@router.get("")
async def move_status(
    request: Request,
    admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    key = await instance_identity.public_key(session)
    move = await instance_identity.active_move(session)
    nodes = []
    rows = (await session.execute(
        select(Node, Network.name).join(Network, Network.id == Node.network_id).order_by(Network.name, Node.hostname)
    )).all()
    for node, network_name in rows:
        nodes.append({
            "id": node.id,
            "hostname": node.hostname,
            "network": network_name,
            "client_version": node.client_version,
            "last_seen": node.last_seen.isoformat() + "Z" if node.last_seen else None,
            "move_ready": bool(node.move_ready),
            "move_state": node.move_state,
            "move_state_at": node.move_state_at.isoformat() + "Z" if node.move_state_at else None,
            "move_error": node.move_error,
        })
    return {
        "fingerprint": instance_identity.fingerprint(key),
        "public_url": _own_url(request),
        "move": _move_view(move) if move else None,
        "nodes": nodes,
        "min_wait_hours": settings.move_min_wait_hours,
        "max_wait_hours": MAX_WAIT_HOURS,
        "default_wait_hours": DEFAULT_WAIT_HOURS,
        "client_foreign_floor_hours": CLIENT_FOREIGN_FLOOR_HOURS,
        "move_client_version": MOVE_CLIENT_VERSION,
        "two_factor_enabled": await mfa.enabled_for_sub(session, admin.sub),
    }


class StartMoveRequest(BaseModel):
    new_url: str
    new_key_fp: str
    wait_hours: int = DEFAULT_WAIT_HOURS
    keep_days: int = 30
    expires_days: int = 365
    reauth_token: str
    totp_code: str


async def _fetch_fingerprint(new_url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            r = await client.get(f"{new_url}/api/instance/fingerprint")
        r.raise_for_status()
        return str(r.json().get("fingerprint") or "")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't reach {new_url} to check its fingerprint ({type(e).__name__}). "
                   "Is it running Nebula Commander 0.9.0 or newer, reachable from this server?",
        ) from e


@router.post("")
async def start_move(
    request: Request,
    body: StartMoveRequest,
    admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    new_url = _normalize_url(body.new_url)
    own = _own_url(request)
    parsed = urlparse(new_url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.path not in ("", "/"):
        raise HTTPException(status_code=400, detail="Enter the new server's address, e.g. https://nc.example.com")
    if parsed.scheme == "http" and urlparse(own).scheme != "http":
        raise HTTPException(status_code=400, detail="The new server must use https")
    if new_url == own:
        raise HTTPException(status_code=400, detail="That is this server")
    if not (settings.move_min_wait_hours <= body.wait_hours <= MAX_WAIT_HOURS):
        raise HTTPException(status_code=400, detail=f"Wait must be {settings.move_min_wait_hours}-{MAX_WAIT_HOURS} hours")
    if not (1 <= body.keep_days <= 365):
        raise HTTPException(status_code=400, detail="Keep the old address answering for 1-365 days")
    if not (body.keep_days <= body.expires_days <= 3650):
        raise HTTPException(status_code=400, detail="Devices must accept the move at least as long as the old address answers")
    new_key_fp = instance_identity.normalize_fingerprint(body.new_key_fp)
    if len(new_key_fp) < 20:
        raise HTTPException(status_code=400, detail="Paste the fingerprint shown on the new server's Move page")
    if await instance_identity.active_move(session) is not None:
        raise HTTPException(status_code=409, detail="A move is already in progress")

    # Checked before the reauth and code are used up, so a typo costs nothing.
    own_fp = instance_identity.fingerprint(await instance_identity.public_key(session))
    if new_key_fp == own_fp:
        raise HTTPException(status_code=400, detail="That fingerprint is this server's own")
    reported = await _fetch_fingerprint(new_url)
    if reported != new_key_fp:
        raise HTTPException(
            status_code=400,
            detail="The fingerprint doesn't match the one the new server reports. Copy it again from the new server's Move page.",
        )

    await require_reauth(admin.sub, body.reauth_token, session)
    await mfa.require_code(session, admin.sub, body.totp_code)

    now = datetime.utcnow().replace(microsecond=0)
    switch_at = now + timedelta(hours=body.wait_hours)
    expires_at = now + timedelta(days=body.expires_days)
    move_id = secrets.token_hex(8)
    stmt = instance_identity.statement_body(move_id, own, new_url, new_key_fp, now, switch_at, expires_at)
    actor = await session.scalar(select(User.id).where(User.oidc_sub == admin.sub))
    move = InstanceMove(
        move_id=move_id, new_url=new_url, new_key_fp=new_key_fp,
        body=stmt.decode("utf-8"), signature=await instance_identity.sign(session, stmt),
        wait_hours=body.wait_hours, keep_days=body.keep_days, created_by_user_id=actor,
        created_at=now, switch_at=switch_at, expires_at=expires_at, status="active",
    )
    session.add(move)
    await log_audit(session, "instance_move_started", actor_user_id=actor, actor_identifier=admin.email,
                    details={"new_url": new_url, "wait_hours": body.wait_hours}, client_ip=get_client_ip(request))
    await session.commit()
    move_middleware.invalidate()
    return _move_view(move)


class CancelMoveRequest(BaseModel):
    reauth_token: str
    totp_code: str


@router.post("/cancel")
async def cancel_move(
    request: Request,
    body: CancelMoveRequest,
    admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    """Stop handing out the statement. Devices that haven't switched yet drop the move
    at their next poll; ones that already switched stay on the new server."""
    move = await instance_identity.active_move(session)
    if move is None:
        raise HTTPException(status_code=404, detail="No move in progress")
    await require_reauth(admin.sub, body.reauth_token, session)
    await mfa.require_code(session, admin.sub, body.totp_code)
    move.status, move.cancelled_at = "cancelled", datetime.utcnow()
    actor = await session.scalar(select(User.id).where(User.oidc_sub == admin.sub))
    await log_audit(session, "instance_move_cancelled", actor_user_id=actor, actor_identifier=admin.email,
                    details={"new_url": move.new_url}, client_ip=get_client_ip(request))
    await session.commit()
    move_middleware.invalidate()
    return {"ok": True}


@router.get("/responder")
async def move_responder_file(
    admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    """move-responder.json for the moved-only mode (NEBULA_COMMANDER_MOVED_ONLY_FILE) and
    contrib/move-responder: the signed statement plus who to email when the recommended
    period ends. Nothing secret in it."""
    move = await instance_identity.active_move(session)
    if move is None:
        raise HTTPException(status_code=404, detail="No move in progress")
    admins = (await session.execute(
        select(User.email).where(User.system_role == "system-admin", User.email.is_not(None))
    )).scalars().all()
    view = _move_view(move)
    data = {
        "v": 1,
        "statement": instance_identity.wire(move.body, move.signature),
        "old_url": json.loads(move.body)["old_url"],
        "new_url": move.new_url,
        "switch_at": view["switch_at"],
        "recommended_until": view["recommended_until"],
        "expires_at": view["expires_at"],
        "admin_emails": sorted({e for e in admins if e and "@" in e}),
    }
    return Response(
        content=json.dumps(data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="move-responder.json"'},
    )
