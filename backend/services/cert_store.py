"""
Read/write cert store files with encryption at rest. All files under cert_store_path
are stored encrypted (magic + Fernet).
"""
from pathlib import Path

from ..config import settings
from ..utils.nebula_cert import _check_path_under_roots
from .encryption import decrypt, encrypt


def read_cert_store_file(path: Path) -> str:
    """Read and decrypt a cert store file; return content as string."""
    safe_path = _check_path_under_roots(path, [Path(settings.cert_store_path)])
    data = safe_path.read_bytes()
    return decrypt(data).decode("utf-8")


def write_cert_store_file(path: Path, content: str) -> None:
    """Encrypt content and write to path."""
    safe_path = _check_path_under_roots(path, [Path(settings.cert_store_path)])
    safe_path.write_bytes(encrypt(content))
    # Restrict permissions for key files (best-effort; Windows may ignore)
    if safe_path.suffix == ".key":
        try:
            safe_path.chmod(0o600)
        except OSError:
            pass
