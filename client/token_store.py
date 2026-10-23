"""
Device token storage: file (when NEBULA_DEVICE_TOKEN_FILE is set) or OS keyring.
Used by ncclient enroll/run; in Docker, set NEBULA_DEVICE_TOKEN_FILE so the token
is stored in a file instead of keyring.
When keyring is not available (e.g. PyInstaller binary without keyring) or not
usable (e.g. a headless server whose Secret Service collection is locked, or no
D-Bus session at all), falls back to ~/.nebula/device-token (mode 0600). That
file is only ever written by the fallback, so when it exists it is the current
token and is read in preference to the keyring.

On Windows, when NEBULA_COMMANDER_CONFIG_DIR is set (see
client/windows/shared_paths.py::enable_shared_mode, used by the Windows service
to share machine-wide state), the token is instead stored DPAPI-encrypted
in machine scope at <that dir>/token.bin - readable by any process on the machine
(not tied to one user's login session, unlike the keyring/Credential Manager
default below), which is what lets a LocalSystem service and an unelevated GUI
client both read/write the same enrolled token. This takes priority over both
NEBULA_DEVICE_TOKEN_FILE and keyring when active.

ncclient 0.8.0+ keeps one token per enrolled network: pass the enrollment id
(client/config.py). With an id the token lives next to where the id-less one would:
<dir of NEBULA_DEVICE_TOKEN_FILE>/tokens/<id>, <config dir>/tokens/<id>.bin (DPAPI),
~/.nebula/tokens/<id> (fallback file) or keyring key device_token:<id>. Without an id
these functions use the pre-0.8.0 single token, which the settings migration moves.
"""
from __future__ import annotations

import os
import sys

__all__ = ["get_token", "set_token", "delete_token"]

_SERVICE = "nebula-commander"
_KEY = "device_token"

# DPAPI flags (from wincrypt.h): suppress any UI prompt (irrelevant for a
# non-interactive service anyway, but explicit) and use the machine key rather
# than the calling user's key, so any process on the machine can decrypt it.
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_CRYPTPROTECT_LOCAL_MACHINE = 0x4


def _safe_id(enrollment_id: str) -> str:
    if not enrollment_id or not all(c.isalnum() or c in "-_" for c in enrollment_id):
        raise ValueError(f"invalid enrollment id {enrollment_id!r}")
    return enrollment_id


def _token_file_path(enrollment_id: str | None = None) -> str | None:
    path = os.environ.get("NEBULA_DEVICE_TOKEN_FILE", "").strip()
    if not path:
        return None
    if enrollment_id:
        return os.path.join(os.path.dirname(path) or ".", "tokens", _safe_id(enrollment_id))
    return path


def _default_token_path(enrollment_id: str | None = None) -> str:
    """Path used when keyring is not available (e.g. Linux binary without keyring)."""
    if enrollment_id:
        return os.path.join(os.path.expanduser("~"), ".nebula", "tokens", _safe_id(enrollment_id))
    return os.path.join(os.path.expanduser("~"), ".nebula", "device-token")


def _keyring_key(enrollment_id: str | None) -> str:
    return f"{_KEY}:{_safe_id(enrollment_id)}" if enrollment_id else _KEY


def _shared_dpapi_active() -> bool:
    return sys.platform == "win32" and bool(os.environ.get("NEBULA_COMMANDER_CONFIG_DIR", "").strip())


def _dpapi_token_path(enrollment_id: str | None = None) -> str:
    from .config import config_dir
    if enrollment_id:
        return os.path.join(config_dir(), "tokens", f"{_safe_id(enrollment_id)}.bin")
    return os.path.join(config_dir(), "token.bin")


def _dpapi_get_token(enrollment_id: str | None = None) -> str | None:
    path = _dpapi_token_path(enrollment_id)
    if not os.path.isfile(path):
        return None
    try:
        import win32crypt
        with open(path, "rb") as f:
            blob = f.read()
        if not blob:
            return None
        _descr, data = win32crypt.CryptUnprotectData(
            blob, None, None, None, _CRYPTPROTECT_UI_FORBIDDEN
        )
        return data.decode("utf-8")
    except Exception:
        return None


def _dpapi_set_token(token: str, enrollment_id: str | None = None) -> None:
    import win32crypt
    path = _dpapi_token_path(enrollment_id)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    blob = win32crypt.CryptProtectData(
        token.encode("utf-8"),
        "nebula-commander-token",
        None,
        None,
        None,
        _CRYPTPROTECT_LOCAL_MACHINE | _CRYPTPROTECT_UI_FORBIDDEN,
    )
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)


def _read_token_file(path: str) -> str | None:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                value = f.read().strip()
            return value if value else None
    except Exception as e:
        print(f"Failed to read token file {path}: {e}", file=sys.stderr)
    return None


def _write_token_file(path: str, token: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.chmod(path, 0o600)  # an existing file keeps its old mode through os.open
    except OSError:
        pass
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)


def get_token(enrollment_id: str | None = None) -> str | None:
    """Read device token: DPAPI shared store (Windows shared-state mode), else file
    (if NEBULA_DEVICE_TOKEN_FILE set), else keyring."""
    if _shared_dpapi_active():
        return _dpapi_get_token(enrollment_id)
    path = _token_file_path(enrollment_id)
    if path:
        return _read_token_file(path)
    fallback = _read_token_file(_default_token_path(enrollment_id))
    if fallback:
        return fallback
    try:
        import keyring
        value = keyring.get_password(_SERVICE, _keyring_key(enrollment_id))
        return value if value else None
    except (ImportError, ModuleNotFoundError):
        return None
    except Exception as e:
        print(f"Keyring read failed: {e}", file=sys.stderr)
        return None


def set_token(token: str, enrollment_id: str | None = None) -> None:
    """Write device token: DPAPI shared store (Windows shared-state mode), else file
    (if NEBULA_DEVICE_TOKEN_FILE set), else keyring."""
    if _shared_dpapi_active():
        _dpapi_set_token(token, enrollment_id)
        return
    path = _token_file_path(enrollment_id)
    if path:
        _write_token_file(path, token)
        return
    fallback = _default_token_path(enrollment_id)
    try:
        import keyring
        keyring.set_password(_SERVICE, _keyring_key(enrollment_id), token)
    except (ImportError, ModuleNotFoundError):
        _write_token_file(fallback, token)
        return
    except Exception as e:
        # KeyringLocked, NoKeyringError, a D-Bus error with no session bus, ...
        _write_token_file(fallback, token)
        print(f"Keyring unavailable ({e}); stored the device token in {fallback} instead.", file=sys.stderr)
        return
    # The keyring now holds the current token; a fallback file left from an
    # earlier enrollment would otherwise shadow it in get_token().
    try:
        os.remove(fallback)
    except FileNotFoundError:
        pass


def delete_token(enrollment_id: str | None = None) -> None:
    """Forget a token (network removed, or the pre-0.8.0 token after the migration
    copied it). Removes every place get_token() may read it from."""
    paths = [_token_file_path(enrollment_id), _default_token_path(enrollment_id)]
    if sys.platform == "win32":
        paths.append(_dpapi_token_path(enrollment_id))
    for path in paths:
        if path:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                print(f"Could not remove token file {path}: {e}", file=sys.stderr)
    if _shared_dpapi_active():
        return
    try:
        import keyring
        keyring.delete_password(_SERVICE, _keyring_key(enrollment_id))
    except Exception:  # nosec B110 - nothing to delete, or no usable keyring: both fine here
        pass
