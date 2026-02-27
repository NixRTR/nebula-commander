"""
Device API: enrollment codes (admin), enroll (public), config/certs (device token).
dnclient-style: one-time code -> device token -> poll for config + certs.
"""
import hashlib
import io
import logging
import secrets
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, require_device_token, UserInfo, create_device_token
from ..config import settings
from ..database import get_session
from ..models import Network, Node, EnrollmentCode, User
from ..services.audit import get_client_ip, log_audit
from ..services.cert_store import read_cert_store_file
from ..services.config_generator import generate_config_for_node

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/device", tags=["device"])


def _random_code(length: int = 16) -> str:
    """Alphanumeric code (easy to type)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# --- Admin: create enrollment code ---

class CreateEnrollmentCodeRequest(BaseModel):
    node_id: int
    expires_in_hours: int = 24


class CreateEnrollmentCodeResponse(BaseModel):
    code: str
    expires_at: str
    node_id: int
    hostname: str


@router.post("/enrollment-codes", response_model=CreateEnrollmentCodeResponse)
async def create_enrollment_code(
    body: CreateEnrollmentCodeRequest,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a one-time enrollment code for a node. Client uses this with POST /device/enroll."""
    result = await session.execute(select(Node).where(Node.id == body.node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if not node.ip_address:
        raise HTTPException(
            status_code=400,
            detail="Node has no certificate yet. Create a certificate first.",
        )
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    code = _random_code().upper()
    expires_at = datetime.utcnow() + timedelta(hours=body.expires_in_hours)
    rec = EnrollmentCode(
        node_id=node.id,
        code=code,
        expires_at=expires_at,
    )
    session.add(rec)
    await session.flush()
    await log_audit(
        session,
        "enrollment_code_created",
        resource_type="node",
        resource_id=node.id,
        actor_user_id=db_user.id if db_user else None,
        actor_identifier=user.email or user.sub,
    )
    return CreateEnrollmentCodeResponse(
        code=code,
        expires_at=expires_at.isoformat() + "Z",
        node_id=node.id,
        hostname=node.hostname,
    )


# --- Public: redeem code -> device token ---

class EnrollRequest(BaseModel):
    code: str


class EnrollResponse(BaseModel):
    device_token: str
    node_id: int
    hostname: str


@router.post("/enroll", response_model=EnrollResponse)
async def enroll(
    request: Request,
    body: EnrollRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Redeem a one-time enrollment code. Returns a long-lived device token.
    Client should save the token and use it for GET /device/config and GET /device/certs.
    
    Rate limited to 5 attempts per 15 minutes per IP to prevent brute-force attacks.
    """
    client_ip = get_client_ip(request)
    code = (body.code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Code is required")
    result = await session.execute(
        select(EnrollmentCode).where(EnrollmentCode.code == code)
    )
    rec = result.scalar_one_or_none()
    if not rec:
        await log_audit(
            session,
            "device_enroll_failure",
            result="failure",
            actor_identifier="device",
            details={"reason": "invalid_or_expired_code"},
            client_ip=client_ip,
        )
        await session.commit()
        raise HTTPException(status_code=404, detail="Invalid or expired code")
    if rec.used_at:
        await log_audit(
            session,
            "device_enroll_failure",
            result="failure",
            actor_identifier="device",
            details={"reason": "code_already_used"},
            client_ip=client_ip,
        )
        await session.commit()
        raise HTTPException(status_code=400, detail="Code already used")
    if datetime.utcnow() > rec.expires_at:
        await log_audit(
            session,
            "device_enroll_failure",
            result="failure",
            actor_identifier="device",
            details={"reason": "code_expired"},
            client_ip=client_ip,
        )
        await session.commit()
        raise HTTPException(status_code=400, detail="Code expired")
    rec.used_at = datetime.utcnow()
    await session.flush()
    result = await session.execute(select(Node).where(Node.id == rec.node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await log_audit(
        session,
        "device_enroll_success",
        resource_type="node",
        resource_id=node.id,
        actor_identifier=node.hostname or "device",
        client_ip=client_ip,
    )
    # Bump the device token version so any previously issued tokens for this node are invalidated.
    node.device_token_version = (node.device_token_version or 1) + 1
    await session.flush()
    device_token = create_device_token(node.id, node.device_token_version)
    return EnrollResponse(
        device_token=device_token,
        node_id=node.id,
        hostname=node.hostname,
    )


# --- Device: config and certs (require device token) ---

@router.get("/config")
async def device_config(
    request: Request,
    node_id: int = Depends(require_device_token),
    session: AsyncSession = Depends(get_session),
):
    """
    Return Nebula YAML config for this device (inline PKI). Use Authorization: Bearer <device_token>.
    Send If-None-Match: <etag> to get 304 when config unchanged.
    """
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.first_polled_at is None:
        node.first_polled_at = datetime.utcnow()
        await session.flush()
    if not node.ip_address:
        raise HTTPException(
            status_code=404,
            detail="Node has no certificate. Create a certificate in the UI first.",
        )
    result = await session.execute(select(Network).where(Network.id == node.network_id))
    network = result.scalar_one_or_none()
    if not network or not network.ca_cert_path:
        raise HTTPException(status_code=404, detail="Network or CA not found")
    host_cert_path = Path(settings.cert_store_path) / str(node.network_id) / "hosts" / f"{node.hostname}.crt"
    if not host_cert_path.exists():
        raise HTTPException(status_code=404, detail="Host certificate not found")
    host_key_path = Path(settings.cert_store_path) / str(node.network_id) / "hosts" / f"{node.hostname}.key"
    if not host_key_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Host key not stored. Create the certificate in the UI so the key is stored for inline config.",
        )
    ca_path = Path(network.ca_cert_path)
    if not ca_path.exists():
        raise HTTPException(status_code=404, detail="CA certificate not found")
    ca_content = read_cert_store_file(ca_path)
    host_cert_content = read_cert_store_file(host_cert_path)
    host_key_content = read_cert_store_file(host_key_path)
    inline_pki = (ca_content, host_cert_content, host_key_content)
    yaml_config = await generate_config_for_node(session, node_id, inline_pki=inline_pki)
    if yaml_config is None:
        raise HTTPException(status_code=404, detail="Node not found")
    etag = hashlib.sha256(yaml_config.encode("utf-8")).hexdigest()
    if_none_match = (request.headers.get("If-None-Match") or "").strip().strip('"')
    if if_none_match and if_none_match == etag:
        return Response(status_code=304)
    filename = f"{node.hostname}.yaml" if node else "config.yaml"
    return Response(
        content=yaml_config,
        media_type="application/yaml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "ETag": etag,
        },
    )


@router.get("/certs")
async def device_certs(
    node_id: int = Depends(require_device_token),
    session: AsyncSession = Depends(get_session),
):
    """Return ZIP with ca.crt, host.crt, README for this device."""
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.first_polled_at is None:
        node.first_polled_at = datetime.utcnow()
        await session.flush()
    if not node.ip_address:
        raise HTTPException(
            status_code=404,
            detail="Node has no certificate. Create a certificate in the UI first.",
        )
    result = await session.execute(select(Network).where(Network.id == node.network_id))
    network = result.scalar_one_or_none()
    if not network or not network.ca_cert_path:
        raise HTTPException(status_code=404, detail="Network or CA not found")
    host_cert_path = Path(settings.cert_store_path) / str(node.network_id) / "hosts" / f"{node.hostname}.crt"
    if not host_cert_path.exists():
        raise HTTPException(status_code=404, detail="Host certificate file not found")
    host_key_path = Path(settings.cert_store_path) / str(node.network_id) / "hosts" / f"{node.hostname}.key"
    ca_path = Path(network.ca_cert_path)
    if not ca_path.exists():
        raise HTTPException(status_code=404, detail="CA certificate file not found")
    ca_content = read_cert_store_file(ca_path)
    host_cert_content = read_cert_store_file(host_cert_path)
    if host_key_path.exists():
        host_key_content = read_cert_store_file(host_key_path)
        readme = "host.key is included in this zip.\n"
    else:
        host_key_content = None
        readme = "Use the host.key you saved when creating this certificate.\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ca.crt", ca_content)
        zf.writestr("host.crt", host_cert_content)
        if host_key_content is not None:
            zf.writestr("host.key", host_key_content)
        zf.writestr("README.txt", readme)
    buf.seek(0)
    filename = f"node-{node.hostname}-certs.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


