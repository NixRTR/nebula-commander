"""
Instance export and import.

An export is a zip (then passphrase-encrypted, see export_crypto) holding every table
as JSON, decrypted through the ORM, plus the decrypted cert store. Because nothing in
it is tied to this instance's ENCRYPTION_KEY, it can be imported into any fresh install,
which re-encrypts everything with its own key.

Import rules:
- Only into a fresh instance (no networks or nodes yet).
- Network, node and most other ids are kept, so device tokens (which carry the node
  id) and cross-references stay valid. User ids are remapped, because the target
  already has its own placeholder user and whoever has signed in.
- A user maps onto an existing target user with the same OIDC sub. When the target uses
  a different identity provider, users become "imported:<old sub>" and are claimed on
  their first login with a verified matching email (see api/auth.py). The admin doing
  the import is matched by email straight away.
"""
import io
import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from sqlalchemy import DateTime, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.db import (
    AccessGrant,
    AllocatedIP,
    BlockedCertificate,
    AuditLog,
    Certificate,
    EnrollmentCode,
    Invitation,
    LegacyDeviceKey,
    Network,
    NetworkDNSAlias,
    NetworkDNSConfig,
    NetworkGroupFirewall,
    NetworkPermission,
    NetworkSettings,
    Node,
    NodePermission,
    SavedTheme,
    User,
)
from .cert_store import read_cert_store_bytes, write_cert_store_bytes
from .encryption import decrypt_to_str, encrypt_to_str

logger = logging.getLogger(__name__)

FORMAT = "nebula-commander-export"
FORMAT_VERSION = 1
MAX_UNCOMPRESSED = 512 * 1024 * 1024
MAX_FILES = 100_000

# Insert order respects foreign keys. Users are handled separately (remapped ids).
TABLES = [
    Network,
    User,
    Node,
    Certificate,
    SavedTheme,
    EnrollmentCode,
    AllocatedIP,
    BlockedCertificate,
    NetworkSettings,
    NetworkDNSConfig,
    NetworkDNSAlias,
    NetworkGroupFirewall,
    NetworkPermission,
    NodePermission,
    AccessGrant,
    Invitation,
    AuditLog,
]
# Columns that reference users.id and must follow the user remapping.
USER_FKS = {
    SavedTheme: ["user_id"],
    NetworkPermission: ["user_id", "invited_by_user_id"],
    NodePermission: ["user_id", "granted_by_user_id"],
    AccessGrant: ["admin_user_id", "granted_by_user_id"],
    Invitation: ["invited_by_user_id"],
    AuditLog: ["actor_user_id"],
}
# Tables whose rows are appended with fresh ids (the target may already have some).
NEW_IDS = {AuditLog}

README = """Nebula Commander instance export
================================

This file is encrypted with the passphrase chosen when it was created, in the
standard age format (https://age-encryption.org). Nobody can open it without
that passphrase, and the passphrase cannot be recovered.

To look inside without Nebula Commander:
    age -d -o export.zip {filename}
or, with the Nebula Commander backend installed:
    python -m backend.scripts.ncexport decrypt {filename} export.zip

To move this instance: install Nebula Commander, sign in as an administrator,
open Backup & export and import this file. Then point each device at the new
server by setting NEBULA_COMMANDER_SERVER. If the export included the device
signing key, enrolled devices keep working without re-enrolling.

Contents: manifest.json, data/<table>.json (all data, decrypted), certs/ (CA and
host certificates and keys, decrypted), device_signing_keys.json (optional: the
secrets that signed this instance's device tokens).
"""


class ExportImportError(Exception):
    """The file can't be imported (message is safe to show to the admin)."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _columns(model) -> list[str]:
    return [c.name for c in model.__table__.columns]


def _source_issuer() -> Optional[str]:
    return (settings.oidc_public_issuer_url or settings.oidc_issuer_url or "").rstrip("/") or None


async def build_export(
    session: AsyncSession, include_device_key: bool, app_version: str, filename: str
) -> bytes:
    """Build the (unencrypted) export zip."""
    counts: dict[str, int] = {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for model in TABLES:
            cols = _columns(model)
            rows = (await session.execute(select(model).order_by(model.id))).scalars().all()
            data = [{c: _jsonable(getattr(r, c)) for c in cols} for r in rows]
            counts[model.__tablename__] = len(data)
            zf.writestr(f"data/{model.__tablename__}.json", json.dumps(data, indent=1))

        root = Path(settings.cert_store_path)
        cert_files, cert_errors = 0, []
        if root.is_dir():
            for path in sorted(p for p in root.rglob("*") if p.is_file()):
                rel = path.relative_to(root).as_posix()
                try:
                    zf.writestr(f"certs/{rel}", read_cert_store_bytes(path))
                    cert_files += 1
                except Exception as e:  # noqa: BLE001 - report, don't abort the whole export
                    cert_errors.append(rel)
                    logger.warning("export: could not read cert store file %s: %s", rel, e)

        if include_device_key:
            # The current secret plus any keys this instance itself imported earlier, so
            # devices keep working across several moves.
            legacy = (await session.execute(select(LegacyDeviceKey.key))).scalars().all()
            keys = [settings.jwt_secret_key] + [decrypt_to_str(k) for k in legacy]
            zf.writestr("device_signing_keys.json", json.dumps(keys))

        manifest = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "app_version": app_version,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "source_public_url": settings.public_url,
            "source_oidc_issuer": _source_issuer(),
            "source_cert_store_path": str(root),
            "counts": counts,
            "cert_files": cert_files,
            "cert_files_unreadable": cert_errors,
            "includes_device_key": include_device_key,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("README.txt", README.format(filename=filename))
    return buf.getvalue()


def read_manifest(zip_bytes: bytes) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            manifest = json.loads(zf.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, ValueError) as e:
        raise ExportImportError("This isn't a Nebula Commander export.") from e
    if manifest.get("format") != FORMAT:
        raise ExportImportError("This isn't a Nebula Commander export.")
    if int(manifest.get("format_version", 0)) > FORMAT_VERSION:
        raise ExportImportError("This export was made by a newer Nebula Commander. Upgrade this instance first.")
    return manifest


async def import_status(session: AsyncSession) -> dict:
    networks = await session.scalar(select(func.count()).select_from(Network)) or 0
    nodes = await session.scalar(select(func.count()).select_from(Node)) or 0
    return {"can_import": networks == 0 and nodes == 0, "networks": networks, "nodes": nodes}


def _row_values(model, raw: dict, keep_id: bool) -> dict:
    values = {}
    for col in model.__table__.columns:
        if col.name not in raw or (col.name == "id" and not keep_id):
            continue  # unknown/missing columns fall back to model defaults
        value = raw[col.name]
        if value is not None and isinstance(col.type, DateTime) and isinstance(value, str):
            value = datetime.fromisoformat(value.rstrip("Z"))
        values[col.name] = value
    return values


def _safe_cert_path(name: str) -> Optional[PurePosixPath]:
    rel = PurePosixPath(name[len("certs/"):])
    if not rel.parts or rel.is_absolute() or any(p in ("..", "") for p in rel.parts):
        return None
    return rel


def _rewrite_ca_path(value: Optional[str], src_root: str, dst_root: Path) -> Optional[str]:
    if not value:
        return value
    src = PurePosixPath(value.replace("\\", "/"))
    try:
        rel = src.relative_to(PurePosixPath(src_root.replace("\\", "/")))
    except ValueError:
        rel = PurePosixPath(*src.parts[-2:])  # "<network_id>/ca.crt"
    return str(dst_root.joinpath(*rel.parts))


async def import_export(session: AsyncSession, zip_bytes: bytes, importer_sub: str, importer_email: Optional[str]) -> dict:
    """Import an export zip into this (fresh) instance. Commits on success; on failure
    rolls back and removes any cert files it wrote."""
    manifest = read_manifest(zip_bytes)
    status = await import_status(session)
    if not status["can_import"]:
        raise ExportImportError(
            "Import only works on a fresh instance (no networks or nodes yet). "
            f"This one has {status['networks']} network(s) and {status['nodes']} node(s)."
        )

    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    infos = zf.infolist()
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
        raise ExportImportError("The export is too large to import.")

    def table(model) -> list[dict]:
        try:
            return json.loads(zf.read(f"data/{model.__tablename__}.json"))
        except KeyError:
            return []

    same_idp = bool(manifest.get("source_oidc_issuer")) and manifest.get("source_oidc_issuer") == _source_issuer()
    dst_root = Path(settings.cert_store_path)
    written: list[Path] = []
    summary: dict[str, Any] = {"inserted": {}, "users_created": 0, "users_matched": 0, "warnings": []}

    try:
        # --- users: map source ids onto target rows -------------------------------
        target_users = (await session.execute(select(User))).scalars().all()
        by_sub = {u.oidc_sub: u for u in target_users}
        sentinel = next((u for u in target_users if u.is_placeholder), None)
        importer = by_sub.get(importer_sub)
        importer_matched = False
        user_map: dict[int, Optional[int]] = {}
        for raw in table(User):
            old_id = raw.get("id")
            if raw.get("is_placeholder"):
                user_map[old_id] = sentinel.id if sentinel else None
                continue
            sub = raw.get("oidc_sub") or ""
            match = by_sub.get(sub)
            if match is None and importer and not importer_matched and importer_email and raw.get("email") \
                    and raw["email"].lower() == importer_email.lower():
                match = importer
                importer_matched = True
            if match is not None:
                if match.theme is None and raw.get("theme"):
                    match.theme = raw["theme"]
                user_map[old_id] = match.id
                summary["users_matched"] += 1
                continue
            if not same_idp and not sub.startswith("imported:"):
                sub = f"imported:{sub}"
            values = _row_values(User, raw, keep_id=False)
            values["oidc_sub"] = sub
            user = User(**values)
            session.add(user)
            await session.flush()
            by_sub[sub] = user
            user_map[old_id] = user.id
            summary["users_created"] += 1

        # --- everything else, in foreign-key order --------------------------------
        for model in TABLES:
            if model is User:
                continue
            rows = table(model)
            fks = USER_FKS.get(model, [])
            inserted = 0
            for raw in rows:
                values = _row_values(model, raw, keep_id=model not in NEW_IDS)
                skip = False
                for fk in fks:
                    if values.get(fk) is not None:
                        mapped = user_map.get(values[fk])
                        if mapped is None:
                            # Dangling reference in the source: nullable -> NULL, else fall
                            # back to the placeholder user (like a deleted user would).
                            col = model.__table__.columns[fk]
                            if col.nullable:
                                mapped = None
                            elif sentinel is not None:
                                mapped = sentinel.id
                            else:
                                skip = True
                        values[fk] = mapped
                if skip:
                    summary["warnings"].append(f"skipped a {model.__tablename__} row with an unknown user")
                    continue
                if model is Network:
                    for col in ("ca_cert_path", "ca_key_path"):
                        values[col] = _rewrite_ca_path(values.get(col), manifest.get("source_cert_store_path", ""), dst_root)
                session.add(model(**values))
                inserted += 1
            if inserted:
                summary["inserted"][model.__tablename__] = inserted
            await session.flush()

        device_key_restored = False
        if "device_signing_keys.json" in zf.namelist():
            existing = {decrypt_to_str(k) for k in (await session.execute(select(LegacyDeviceKey.key))).scalars()}
            for key in json.loads(zf.read("device_signing_keys.json")):
                if not isinstance(key, str) or not key:
                    continue
                device_key_restored = True
                if key != settings.jwt_secret_key and key not in existing:
                    session.add(LegacyDeviceKey(key=encrypt_to_str(key), source=manifest.get("source_public_url")))
                    existing.add(key)
        await session.flush()

        # --- cert store: only once all rows went in cleanly ---------------------------
        cert_files = 0
        for name in zf.namelist():
            if not name.startswith("certs/") or name.endswith("/"):
                continue
            rel = _safe_cert_path(name)
            if rel is None:
                summary["warnings"].append(f"skipped unsafe path {name}")
                continue
            dest = dst_root.joinpath(*rel.parts)
            write_cert_store_bytes(dest, zf.read(name))
            written.append(dest)
            cert_files += 1

        await session.commit()
    except Exception:
        await session.rollback()
        for path in written:
            try:
                path.unlink()
            except OSError:
                pass
        raise

    summary.update(
        cert_files=cert_files,
        device_key_restored=device_key_restored,
        same_identity_provider=same_idp,
        source_public_url=manifest.get("source_public_url"),
        source_app_version=manifest.get("app_version"),
        exported_at=manifest.get("created_at"),
    )
    return summary
