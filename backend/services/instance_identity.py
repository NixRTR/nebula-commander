"""
This instance's Ed25519 identity key and the signed move statement (backend/api/move.py).

Devices pin the public key (GET /api/device/info, enroll) and only follow a move
statement signed with it. The instance being moved to proves itself to each device
by signing the device's nonce with its own key, whose fingerprint the admin pasted
into the old instance (POST /api/device/move-proof).

Statement wire format, in the X-Nebula-Commander-Move header and GET /api/device/move:
    <base64url(body)>.<base64url(signature)>   (no padding)
where body is compact JSON with sorted keys and the signature covers those exact bytes.
"""
import base64
import hashlib
import json
from datetime import datetime
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import InstanceKey, InstanceMove
from .encryption import decrypt_to_str, encrypt_to_str

MOVE_HEADER = "X-Nebula-Commander-Move"
STATEMENT_VERSION = 1
# Domain separation for what the new instance signs for a device.
PROOF_PREFIX = "nc-move-proof-v1"

_cached: Optional[tuple[Ed25519PrivateKey, str]] = None


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def fingerprint(public_key_b64: str) -> str:
    """SHA256:<base64> of the raw public key, as ssh shows key fingerprints."""
    raw = base64.b64decode(public_key_b64)
    digest = base64.b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode("ascii")
    return f"SHA256:{digest}"


def normalize_fingerprint(value: str) -> str:
    """What an admin pastes: tolerate whitespace and a missing SHA256: prefix."""
    v = "".join((value or "").split())
    if v and not v.upper().startswith("SHA256:"):
        v = "SHA256:" + v
    return "SHA256:" + v[7:] if v else ""


async def get_instance_key(session: AsyncSession) -> tuple[Ed25519PrivateKey, str]:
    """(private key, base64 public key), created on first use. With several workers
    racing to create it, everyone settles on the lowest id."""
    global _cached
    if _cached is not None:
        return _cached
    row = (await session.execute(select(InstanceKey).order_by(InstanceKey.id).limit(1))).scalar_one_or_none()
    if row is None:
        key = Ed25519PrivateKey.generate()
        raw_priv = key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
        )
        raw_pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        session.add(InstanceKey(
            private_key=encrypt_to_str(base64.b64encode(raw_priv).decode("ascii")),
            public_key=base64.b64encode(raw_pub).decode("ascii"),
        ))
        await session.commit()
        row = (await session.execute(select(InstanceKey).order_by(InstanceKey.id).limit(1))).scalar_one()
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(decrypt_to_str(row.private_key)))
    _cached = (key, row.public_key)
    return _cached


def reset_cache() -> None:
    """Tests run several instances in one process."""
    global _cached
    _cached = None


async def public_key(session: AsyncSession) -> str:
    return (await get_instance_key(session))[1]


async def sign(session: AsyncSession, data: bytes) -> str:
    key, _ = await get_instance_key(session)
    return b64url(key.sign(data))


def proof_message(nonce: str, node_id: int, new_url: str) -> bytes:
    return f"{PROOF_PREFIX}|{nonce}|{node_id}|{new_url}".encode("utf-8")


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"


def statement_body(
    move_id: str, old_url: str, new_url: str, new_key_fp: str,
    created_at: datetime, switch_at: datetime, expires_at: datetime,
) -> bytes:
    return json.dumps({
        "v": STATEMENT_VERSION,
        "move_id": move_id,
        "old_url": old_url,
        "new_url": new_url,
        "new_key_fp": new_key_fp,
        "created_at": _iso(created_at),
        "switch_at": _iso(switch_at),
        "expires_at": _iso(expires_at),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")


def wire(body: str | bytes, signature: str) -> str:
    raw = body.encode("utf-8") if isinstance(body, str) else body
    return f"{b64url(raw)}.{signature}"


async def active_move(session: AsyncSession) -> Optional[InstanceMove]:
    result = await session.execute(
        select(InstanceMove)
        .where(InstanceMove.status == "active", InstanceMove.expires_at > datetime.utcnow())
        .order_by(InstanceMove.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def move_header_value(session: AsyncSession) -> Optional[str]:
    move = await active_move(session)
    return wire(move.body, move.signature) if move else None
