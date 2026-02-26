"""
Read/write cert store files with encryption at rest. All files under cert_store_path
are stored encrypted (magic + Fernet).
"""
from pathlib import Path

from .encryption import decrypt, encrypt


def read_cert_store_file(path: Path) -> str:
    """Read and decrypt a cert store file; return content as string."""
    data = path.read_bytes()
    return decrypt(data).decode("utf-8")


def write_cert_store_file(path: Path, content: str) -> None:
    """Encrypt content and write to path."""
    path.write_bytes(encrypt(content))
    # Restrict permissions for key files (best-effort; Windows may ignore)
    if path.suffix == ".key":
        try:
            path.chmod(0o600)
        except OSError:
            pass
