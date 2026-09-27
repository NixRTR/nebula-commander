"""
Backup & export: self-service, passphrase-encrypted export of the whole instance,
and import of such an export into a fresh instance. System admins only, and both
actions require a fresh reauthentication (same step-up flow as deleting a network).

The passphrase only ever lives in the request that uses it: it is never stored,
logged, or included in audit details or error messages.
"""
import logging
import os
import re
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import UserInfo
from ..auth.permissions import require_system_admin
from ..auth.reauth import clear_reauth_challenge, decode_reauth_token, verify_reauth
from ..config import settings
from ..database import get_session
from ..models.db import User
from ..services import export_crypto
from ..services.audit import get_client_ip, log_audit
from ..services.instance_export import ExportImportError, build_export, import_export, import_status, read_manifest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["backup"])

MAX_IMPORT_BYTES = 100 * 1024 * 1024
APP_VERSION = os.getenv("VERSION", "dev")


class ExportRequest(BaseModel):
    reauth_token: str
    passphrase: str
    include_device_key: bool = True

    def __repr__(self) -> str:  # keep the passphrase out of any accidental logging
        return f"ExportRequest(include_device_key={self.include_device_key})"


async def _require_reauth(admin: UserInfo, reauth_token: str, session: AsyncSession) -> None:
    payload = decode_reauth_token(reauth_token)
    if not payload or payload.get("sub") != admin.sub:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired reauthentication")
    if not await verify_reauth(admin.sub, payload.get("challenge"), session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reauthentication required")
    await clear_reauth_challenge(admin.sub, session)  # single use


def _check_passphrase(passphrase: str) -> None:
    if len(passphrase) < export_crypto.MIN_PASSPHRASE_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Passphrase must be at least {export_crypto.MIN_PASSPHRASE_LENGTH} characters",
        )


async def _actor_id(session: AsyncSession, admin: UserInfo):
    return await session.scalar(select(User.id).where(User.oidc_sub == admin.sub))


def _export_filename() -> str:
    host = urlparse(settings.public_url or "").hostname or "instance"
    host = re.sub(r"[^A-Za-z0-9.-]", "-", host)
    return f"nebula-commander-{host}-{datetime.utcnow():%Y%m%d-%H%M}.ncexport.age"


@router.get("/backup/status")
async def backup_status(
    admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    return {
        **await import_status(session),
        "min_passphrase_length": export_crypto.MIN_PASSPHRASE_LENGTH,
        "public_url": settings.public_url,
    }


@router.post("/export")
async def export_instance(
    body: ExportRequest,
    request: Request,
    admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    """Download the whole instance, encrypted with the admin's passphrase (age format)."""
    await _require_reauth(admin, body.reauth_token, session)
    _check_passphrase(body.passphrase)
    filename = _export_filename()
    try:
        archive = await build_export(session, body.include_device_key, APP_VERSION, filename)
        encrypted = export_crypto.encrypt(archive, body.passphrase)
    except Exception:
        logger.exception("instance export failed")
        raise HTTPException(status_code=500, detail="Export failed; see server logs") from None
    finally:
        body.passphrase = ""
    await log_audit(
        session,
        "instance_export",
        resource_type="instance",
        actor_user_id=await _actor_id(session, admin),
        actor_identifier=admin.email or admin.sub,
        details={"bytes": len(encrypted), "include_device_key": body.include_device_key},
        client_ip=get_client_ip(request),
    )
    await session.commit()
    return Response(
        content=encrypted,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/import")
async def import_instance(
    request: Request,
    file: UploadFile = File(...),
    passphrase: str = Form(...),
    reauth_token: str = Form(...),
    admin: UserInfo = Depends(require_system_admin),
    session: AsyncSession = Depends(get_session),
):
    """Import an export into this instance (only while it has no networks or nodes)."""
    await _require_reauth(admin, reauth_token, session)
    await session.commit()  # the challenge is spent even if the import fails
    data = await file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Export file is too large")
    try:
        archive = export_crypto.decrypt(data, passphrase)
    except export_crypto.ExportDecryptError:
        raise HTTPException(status_code=400, detail="Wrong passphrase, or this isn't a Nebula Commander export") from None
    finally:
        passphrase = ""
    try:
        read_manifest(archive)
        summary = await import_export(session, archive, admin.sub, admin.email)
    except ExportImportError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception:
        logger.exception("instance import failed")
        raise HTTPException(status_code=500, detail="Import failed; nothing was changed. See server logs.") from None
    await log_audit(
        session,
        "instance_import",
        resource_type="instance",
        actor_user_id=await _actor_id(session, admin),
        actor_identifier=admin.email or admin.sub,
        details={
            "source": summary.get("source_public_url"),
            "inserted": summary.get("inserted"),
            "users_created": summary.get("users_created"),
            "device_key_restored": summary.get("device_key_restored"),
        },
        client_ip=get_client_ip(request),
    )
    await session.commit()
    return summary
