"""
Instance export -> import between two independent "instances": separate SQLite DBs,
cert stores, encryption keys, JWT secrets and (by default) identity providers.
"""
import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api.auth import _claim_imported_user
from backend.auth.oidc import require_device_token
from backend.config import settings
from backend.database import Base
from backend.models import (
    AuditLog,
    EnrollmentCode,
    Invitation,
    LegacyDeviceKey,
    Network,
    NetworkPermission,
    Node,
    User,
)
from backend.services import encryption, export_crypto
from backend.services.cert_store import read_cert_store_bytes, write_cert_store_bytes
from backend.services.instance_export import ExportImportError, build_export, import_export

CA_PEM = b"-----BEGIN NEBULA CERTIFICATE-----\nfake-ca\n-----END NEBULA CERTIFICATE-----\n"
CA_KEY = b"-----BEGIN NEBULA ED25519 PRIVATE KEY-----\nfake-key\n-----END NEBULA ED25519 PRIVATE KEY-----\n"


class Instance:
    def __init__(self, tmp: Path, name: str, issuer: str):
        self.root = tmp / name / "certs"
        self.root.mkdir(parents=True)
        self.db = tmp / name / "db.sqlite"
        self.key = Fernet.generate_key().decode()
        self.jwt = f"jwt-secret-{name}-0123456789abcdef"
        self.issuer = issuer
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db}")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    def activate(self):
        """Point the process-global settings at this instance."""
        settings._encryption_key = self.key
        encryption._fernet = None
        settings.cert_store_path = str(self.root)
        settings.jwt_secret_key = self.jwt
        settings.oidc_issuer_url = self.issuer
        settings.oidc_public_issuer_url = self.issuer
        settings.public_url = f"https://{self.root.parent.name}.example.com"

    async def create(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with self.sessions() as s:
            s.add(User(oidc_sub="system:deleted-user", email="Deleted user", is_placeholder=True))
            await s.commit()


@pytest_asyncio.fixture
async def instances(tmp_path):
    saved = {k: getattr(settings, k) for k in
             ("_encryption_key", "cert_store_path", "jwt_secret_key", "oidc_issuer_url",
              "oidc_public_issuer_url", "public_url")}
    src = Instance(tmp_path, "source", "https://idp-old.example.com/realms/a")
    dst = Instance(tmp_path, "target", "https://idp-new.example.com/realms/b")
    for inst in (src, dst):
        inst.activate()
        await inst.create()
    yield src, dst
    for inst in (src, dst):
        await inst.engine.dispose()
    for k, v in saved.items():
        setattr(settings, k, v)
    encryption._fernet = None


async def seed_source(src: Instance) -> None:
    src.activate()
    write_cert_store_bytes(src.root / "1" / "ca.crt", CA_PEM)
    write_cert_store_bytes(src.root / "1" / "ca.key", CA_KEY)
    write_cert_store_bytes(src.root / "1" / "hosts" / "laptop.crt", b"host-cert")
    async with src.sessions() as s:
        admin = User(oidc_sub="old-admin", email="admin@example.com", system_role="system-admin",
                     theme={"primary": {"light": "#111111", "dark": "#222222"}})
        bob = User(oidc_sub="old-bob", email="bob@example.com")
        s.add_all([admin, bob])
        await s.flush()
        s.add(Network(id=1, name="office", subnet_cidr="10.42.0.0/24",
                      ca_cert_path=str(src.root / "1" / "ca.crt"), ca_key_path=str(src.root / "1" / "ca.key")))
        await s.flush()
        s.add(Node(id=7, network_id=1, hostname="laptop", ip_address="10.42.0.7",
                   public_key="PUBKEY-PLAINTEXT", status="active", device_token_version=3))
        await s.flush()
        s.add_all([
            EnrollmentCode(node_id=7, code="ENROLL1234", expires_at=datetime.utcnow() + timedelta(days=1)),
            NetworkPermission(user_id=bob.id, network_id=1, role="member", invited_by_user_id=admin.id),
            Invitation(email="carol@example.com", network_id=1, invited_by_user_id=admin.id,
                       token="INVITE-TOKEN", role="member", expires_at=datetime.utcnow() + timedelta(days=7)),
            AuditLog(action="network_create", actor_user_id=admin.id, actor_identifier="admin@example.com"),
        ])
        await s.commit()


async def export_from(src: Instance, include_device_key=True) -> bytes:
    src.activate()
    async with src.sessions() as s:
        archive = await build_export(s, include_device_key, "test", "x.ncexport.age")
    # through the real encryption, as the endpoint does
    return export_crypto.decrypt(export_crypto.encrypt(archive, "a long enough passphrase"), "a long enough passphrase")


async def add_importer(dst: Instance, sub="new-admin", email="ADMIN@example.com") -> None:
    dst.activate()
    async with dst.sessions() as s:
        s.add(User(oidc_sub=sub, email=email, system_role="system-admin"))
        s.add(AuditLog(action="auth_login_success", actor_identifier=email))
        await s.commit()


@pytest.mark.asyncio
async def test_export_import_different_key_and_idp(instances):
    src, dst = instances
    await seed_source(src)
    archive = await export_from(src)

    manifest = json.loads(zipfile.ZipFile(io.BytesIO(archive)).read("manifest.json"))
    assert manifest["counts"]["nodes"] == 1 and manifest["cert_files"] == 3

    await add_importer(dst)
    async with dst.sessions() as s:
        summary = await import_export(s, archive, "new-admin", "ADMIN@example.com")
    assert summary["users_created"] == 1 and summary["users_matched"] == 1
    assert summary["device_key_restored"] and not summary["same_identity_provider"]

    async with dst.sessions() as s:
        importer = await s.scalar(select(User).where(User.oidc_sub == "new-admin"))
        bob = await s.scalar(select(User).where(User.email == "bob@example.com"))
        assert bob.oidc_sub == "imported:old-bob"
        assert importer.theme == {"primary": {"light": "#111111", "dark": "#222222"}}
        assert await s.scalar(select(User).where(User.is_placeholder.is_(True)).with_only_columns(
            text("count(*)"))) == 1

        net = await s.get(Network, 1)
        assert net.ca_cert_path == str(dst.root / "1" / "ca.crt")
        assert read_cert_store_bytes(Path(net.ca_key_path)) == CA_KEY  # re-encrypted with the target key
        assert read_cert_store_bytes(dst.root / "1" / "hosts" / "laptop.crt") == b"host-cert"

        node = await s.get(Node, 7)  # id preserved for device tokens
        assert node.public_key == "PUBKEY-PLAINTEXT" and node.device_token_version == 3

        perm = (await s.execute(select(NetworkPermission))).scalar_one()
        assert perm.user_id == bob.id and perm.invited_by_user_id == importer.id
        inv = (await s.execute(select(Invitation))).scalar_one()
        assert inv.token == "INVITE-TOKEN" and inv.invited_by_user_id == importer.id
        assert (await s.execute(select(EnrollmentCode))).scalar_one().code == "ENROLL1234"
        actions = [a.action for a in (await s.execute(select(AuditLog).order_by(AuditLog.id))).scalars()]
        assert actions == ["auth_login_success", "network_create"]
        stored = (await s.execute(select(LegacyDeviceKey))).scalar_one().key
        assert stored != src.jwt and encryption.decrypt_to_str(stored) == src.jwt  # encrypted at rest


@pytest.mark.asyncio
async def test_devices_keep_working_with_imported_signing_key(instances):
    src, dst = instances
    await seed_source(src)
    archive = await export_from(src)
    await add_importer(dst)
    async with dst.sessions() as s:
        await import_export(s, archive, "new-admin", "ADMIN@example.com")

    def token(secret, version=3):
        return jwt.encode({"sub": "device", "node_id": 7, "ver": version,
                           "exp": datetime.utcnow() + timedelta(days=1)}, secret, algorithm="HS256")

    dst.activate()
    async with dst.sessions() as s:
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token(src.jwt))
        assert await require_device_token(credentials=creds, session=s) == 7
        for bad in (token("some-other-secret-xxxxxxxxxxxxxxxx"), token(src.jwt, version=2)):
            with pytest.raises(HTTPException) as e:
                await require_device_token(credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=bad), session=s)
            assert e.value.status_code == 401

    # A second move carries both the target's own key and the one it imported.
    async with dst.sessions() as s:
        again = await build_export(s, True, "test", "y.ncexport.age")
    keys = json.loads(zipfile.ZipFile(io.BytesIO(again)).read("device_signing_keys.json"))
    assert keys == [dst.jwt, src.jwt]


@pytest.mark.asyncio
async def test_without_device_key(instances):
    src, dst = instances
    await seed_source(src)
    archive = await export_from(src, include_device_key=False)
    assert "device_signing_keys.json" not in zipfile.ZipFile(io.BytesIO(archive)).namelist()
    await add_importer(dst)
    async with dst.sessions() as s:
        summary = await import_export(s, archive, "new-admin", "ADMIN@example.com")
        assert not summary["device_key_restored"]
        assert (await s.execute(select(LegacyDeviceKey))).first() is None


@pytest.mark.asyncio
async def test_same_idp_keeps_subs(instances):
    src, dst = instances
    dst.issuer = src.issuer
    await seed_source(src)
    archive = await export_from(src)
    await add_importer(dst, sub="old-admin", email="admin@example.com")
    async with dst.sessions() as s:
        summary = await import_export(s, archive, "old-admin", "admin@example.com")
        assert summary["same_identity_provider"]
        assert (await s.scalar(select(User).where(User.email == "bob@example.com"))).oidc_sub == "old-bob"


@pytest.mark.asyncio
async def test_refuses_non_fresh_instance_and_leaves_it_untouched(instances):
    src, dst = instances
    await seed_source(src)
    archive = await export_from(src)
    await add_importer(dst)
    async with dst.sessions() as s:
        s.add(Network(id=5, name="existing", subnet_cidr="10.9.0.0/24"))
        await s.commit()
    async with dst.sessions() as s:
        with pytest.raises(ExportImportError, match="fresh instance"):
            await import_export(s, archive, "new-admin", "ADMIN@example.com")
    assert not (dst.root / "1").exists()


@pytest.mark.asyncio
async def test_failed_import_rolls_back_and_removes_cert_files(instances, monkeypatch):
    src, dst = instances
    await seed_source(src)
    archive = await export_from(src)
    await add_importer(dst)
    from backend.services import instance_export as ie

    real_write = ie.write_cert_store_bytes
    calls = {"n": 0}

    def flaky(path, content):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        real_write(path, content)

    monkeypatch.setattr(ie, "write_cert_store_bytes", flaky)
    async with dst.sessions() as s:
        with pytest.raises(OSError):
            await import_export(s, archive, "new-admin", "ADMIN@example.com")
    async with dst.sessions() as s:
        assert await s.get(Network, 1) is None
    assert not [p for p in dst.root.rglob("*") if p.is_file()]


@pytest.mark.asyncio
async def test_claim_imported_user_requires_verified_email(instances):
    _, dst = instances
    dst.activate()
    async with dst.sessions() as s:
        s.add(User(oidc_sub="imported:old-bob", email="Bob@Example.com"))
        await s.commit()
    async with dst.sessions() as s:
        assert await _claim_imported_user(s, {"email": "bob@example.com", "email_verified": False}, "new-bob", None) is None
        assert await _claim_imported_user(s, {"email": "bob@example.com"}, "new-bob", None) is None
        assert await _claim_imported_user(s, {"email": "eve@example.com", "email_verified": True}, "new-eve", None) is None
        user = await _claim_imported_user(s, {"email": "bob@example.com", "email_verified": True}, "new-bob", None)
        assert user is not None and user.oidc_sub == "new-bob"


def test_export_crypto_rejects_short_passphrase():
    with pytest.raises(ValueError):
        export_crypto.encrypt(b"x", "short")
