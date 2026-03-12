"""
Device token storage via OS credential store (keyring).
Token is read/written only from keyring; no file storage.
"""
from __future__ import annotations

__all__ = ["get_token", "set_token"]

_SERVICE = "nebula-commander"
_KEY = "device_token"


def get_token() -> str | None:
    """Read device token from keyring. Returns None if unavailable or no entry."""
    try:
        import keyring
        value = keyring.get_password(_SERVICE, _KEY)
        return value if value else None
    except Exception:
        return None


def set_token(token: str) -> None:
    """Write device token to keyring. Does not write any file."""
    import keyring
    keyring.set_password(_SERVICE, _KEY, token)
