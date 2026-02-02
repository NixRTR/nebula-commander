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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, require_device_token, UserInfo, create_device_token
from ..config import settings
from ..database import get_session
from ..models import Network, Node, EnrollmentCode
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
    _user: UserInfo = Depends(require_user),
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
    code = _random_code().upper()
    expires_at = datetime.utcnow() + timedelta(hours=body.expires_in_hours)
    rec = EnrollmentCode(
        node_id=node.id,
        code=code,
        expires_at=expires_at,
    )
    session.add(rec)
    await session.flush()
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
    body: EnrollRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Redeem a one-time enrollment code. Returns a long-lived device token.
    Client should save the token and use it for GET /device/config and GET /device/certs.
    """
    code = (body.code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Code is required")
    result = await session.execute(
        select(EnrollmentCode).where(EnrollmentCode.code == code)
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Invalid or expired code")
    if rec.used_at:
        raise HTTPException(status_code=400, detail="Code already used")
    if datetime.utcnow() > rec.expires_at:
        raise HTTPException(status_code=400, detail="Code expired")
    rec.used_at = datetime.utcnow()
    await session.flush()
    result = await session.execute(select(Node).where(Node.id == rec.node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    device_token = create_device_token(node.id)
    return EnrollResponse(
        device_token=device_token,
        node_id=node.id,
        hostname=node.hostname,
    )


# --- Device: config and certs (require device token) ---

@router.get("/config")
async def device_config(
    node_id: int = Depends(require_device_token),
    session: AsyncSession = Depends(get_session),
):
    """Return Nebula YAML config for this device. Use Authorization: Bearer <device_token>."""
    yaml_config = await generate_config_for_node(session, node_id)
    if yaml_config is None:
        raise HTTPException(status_code=404, detail="Node not found")
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    filename = f"{node.hostname}.yaml" if node else "config.yaml"
    return Response(
        content=yaml_config,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
    ca_path = Path(network.ca_cert_path)
    if not ca_path.exists():
        raise HTTPException(status_code=404, detail="CA certificate file not found")
    ca_content = ca_path.read_text()
    host_cert_content = host_cert_path.read_text()
    readme = "Use the host.key you saved when creating this certificate.\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ca.crt", ca_content)
        zf.writestr("host.crt", host_cert_content)
        zf.writestr("README.txt", readme)
    buf.seek(0)
    filename = f"node-{node.hostname}-certs.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/bundle")
async def device_bundle(
    node_id: int = Depends(require_device_token),
    session: AsyncSession = Depends(get_session),
):
    """
    Return a single ZIP with config.yaml, ca.crt, host.crt, README.txt.
    Client can poll this once per minute and extract all files (dnclient-style).
    """
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if not node.ip_address:
        raise HTTPException(
            status_code=404,
            detail="Node has no certificate. Create a certificate in the UI first.",
        )
    yaml_config = await generate_config_for_node(session, node_id)
    if yaml_config is None:
        raise HTTPException(status_code=404, detail="Node not found")
    result = await session.execute(select(Network).where(Network.id == node.network_id))
    network = result.scalar_one_or_none()
    if not network or not network.ca_cert_path:
        raise HTTPException(status_code=404, detail="Network or CA not found")
    host_cert_path = Path(settings.cert_store_path) / str(node.network_id) / "hosts" / f"{node.hostname}.crt"
    if not host_cert_path.exists():
        raise HTTPException(status_code=404, detail="Host certificate file not found")
    ca_path = Path(network.ca_cert_path)
    if not ca_path.exists():
        raise HTTPException(status_code=404, detail="CA certificate file not found")
    ca_content = ca_path.read_text()
    host_cert_content = host_cert_path.read_text()
    readme = "Place host.key (saved when you created the certificate) in the same directory.\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("config.yaml", yaml_config)
        zf.writestr("ca.crt", ca_content)
        zf.writestr("host.crt", host_cert_content)
        zf.writestr("README.txt", readme)
    buf.seek(0)
    zip_bytes = buf.getvalue()
    etag = hashlib.sha256(zip_bytes).hexdigest()
    filename = f"nebula-{node.hostname}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "ETag": etag,
        },
    )
