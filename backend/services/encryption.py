"""
Encryption at rest: Fernet (symmetric, authenticated) with a version magic prefix.
Used for sensitive DB columns and cert store files. Key is required at startup.
"""
import base64
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

logger = logging.getLogger(__name__)

# Version magic for future key-rotation or format changes
MAGIC = b"NCENC\x01"

_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """Lazy-init Fernet from key loaded at startup."""
    global _fernet
    if _fernet is None:
        key = getattr(settings, "_encryption_key", None)
        if not key:
            raise RuntimeError(
                "Encryption key not loaded. Set NEBULA_COMMANDER_ENCRYPTION_KEY or "
                "NEBULA_COMMANDER_ENCRYPTION_KEY_FILE."
            )
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(plaintext: str | bytes) -> bytes:
    """Encrypt plaintext; return magic + Fernet token (bytes)."""
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")
    f = _get_fernet()
    token = f.encrypt(plaintext)
    return MAGIC + token


def decrypt(ciphertext: bytes) -> bytes:
    """Decrypt ciphertext (must start with magic). Invalid/missing magic or failure raises."""
    if not ciphertext or not ciphertext.startswith(MAGIC):
        raise ValueError("Invalid or missing encryption magic; data is not encrypted")
    token = ciphertext[len(MAGIC) :]
    f = _get_fernet()
    try:
        return f.decrypt(token)
    except InvalidToken as e:
        raise ValueError("Decryption failed (invalid token or wrong key)") from e


def encrypt_to_str(plaintext: str | bytes) -> str:
    """Encrypt and return as base64 string (for DB Text columns)."""
    return base64.b64encode(encrypt(plaintext)).decode("ascii")


def decrypt_from_str(ciphertext_b64: str) -> bytes:
    """Decrypt from base64 string (from DB)."""
    raw = base64.b64decode(ciphertext_b64, validate=True)
    return decrypt(raw)


def decrypt_to_str(ciphertext_b64: str) -> str:
    """Decrypt from base64 string and return UTF-8 str (for DB Text columns)."""
    return decrypt_from_str(ciphertext_b64).decode("utf-8")
