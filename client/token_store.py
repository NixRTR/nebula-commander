"""
Device token storage: file (when NEBULA_DEVICE_TOKEN_FILE is set) or OS keyring.
Used by ncclient enroll/run; in Docker, set NEBULA_DEVICE_TOKEN_FILE so the token
is stored in a file instead of keyring.
When keyring is not available (e.g. PyInstaller binary without keyring), falls back
to ~/.nebula/device-token.
"""
from __future__ import annotations

import os

__all__ = ["get_token", "set_token"]

_SERVICE = "nebula-commander"
_KEY = "device_token"


def _token_file_path() -> str | None:
    path = os.environ.get("NEBULA_DEVICE_TOKEN_FILE", "").strip()
    return path or None


def _default_token_path() -> str:
    """Path used when keyring is not available (e.g. Linux binary without keyring)."""
    return os.path.join(os.path.expanduser("~"), ".nebula", "device-token")


def _read_token_file(path: str) -> str | None:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                value = f.read().strip()
            return value if value else None
    except Exception:
        pass
    return None


def _write_token_file(path: str, token: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(token)


def get_token() -> str | None:
    """Read device token from file (if NEBULA_DEVICE_TOKEN_FILE set) or keyring."""
    path = _token_file_path()
    if path:
        return _read_token_file(path)
    try:
        import keyring
        value = keyring.get_password(_SERVICE, _KEY)
        return value if value else None
    except (ImportError, ModuleNotFoundError):
        return _read_token_file(_default_token_path())
    except Exception:
        return None


def set_token(token: str) -> None:
    """Write device token to file (if NEBULA_DEVICE_TOKEN_FILE set) or keyring."""
    path = _token_file_path()
    if path:
        _write_token_file(path, token)
        return
    try:
        import keyring
        keyring.set_password(_SERVICE, _KEY, token)
    except (ImportError, ModuleNotFoundError):
        _write_token_file(_default_token_path(), token)
