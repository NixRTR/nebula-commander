"""
Device token storage: file (when NEBULA_DEVICE_TOKEN_FILE is set) or OS keyring.
Used by ncclient enroll/run; in Docker, set NEBULA_DEVICE_TOKEN_FILE so the token
is stored in a file instead of keyring.
"""
from __future__ import annotations

import os

__all__ = ["get_token", "set_token"]

_SERVICE = "nebula-commander"
_KEY = "device_token"


def _token_file_path() -> str | None:
    path = os.environ.get("NEBULA_DEVICE_TOKEN_FILE", "").strip()
    return path or None


def get_token() -> str | None:
    """Read device token from file (if NEBULA_DEVICE_TOKEN_FILE set) or keyring."""
    path = _token_file_path()
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                value = f.read().strip()
            return value if value else None
        except Exception:
            return None
    try:
        import keyring
        value = keyring.get_password(_SERVICE, _KEY)
        return value if value else None
    except Exception:
        return None


def set_token(token: str) -> None:
    """Write device token to file (if NEBULA_DEVICE_TOKEN_FILE set) or keyring."""
    path = _token_file_path()
    if path:
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(token)
            return
        except Exception:
            raise
    import keyring
    keyring.set_password(_SERVICE, _KEY, token)
