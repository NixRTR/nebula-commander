"""
Read/write cert store files with encryption at rest. All files under cert_store_path
are stored encrypted (magic + Fernet).
"""
import re
from pathlib import Path

from ..config import settings
from ..utils.nebula_cert import _check_path_under_roots
from .encryption import decrypt, encrypt

# Names accepted for new nodes: a DNS-style label set, usable as one path segment.
NODE_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62})$")


def validate_node_name(name: str) -> str:
    """Strip and validate a node name supplied by a client; raises ValueError."""
    name = (name or "").strip()
    if not NODE_NAME_RE.fullmatch(name):
        raise ValueError(
            "Node name must be 1-63 characters of letters, digits, '.', '_' or '-', "
            "starting with a letter or digit"
        )
    return name


def host_file_path(network_id: int, hostname: str, ext: str) -> Path:
    """cert_store/<network_id>/hosts/<hostname><ext>, refusing any hostname that would
    land outside that network's hosts directory. Looser than validate_node_name so
    nodes created before it existed keep working."""
    if not hostname or "/" in hostname or "\\" in hostname or "\0" in hostname or hostname.startswith("."):
        raise ValueError(f"Unsafe node name for a cert store path: {hostname!r}")
    hosts_dir = Path(settings.cert_store_path) / str(int(network_id)) / "hosts"
    path = hosts_dir / f"{hostname}{ext}"
    _check_path_under_roots(path, [hosts_dir])
    return path


def host_cert_path(network_id: int, hostname: str) -> Path:
    """Where a host's current certificate lives in the cert store."""
    return host_file_path(network_id, hostname, ".crt")


def host_key_path(network_id: int, hostname: str) -> Path:
    """Where a host's private key (server-generated keypairs only) lives in the cert store."""
    return host_file_path(network_id, hostname, ".key")


def read_cert_store_file(path: Path) -> str:
    """Read and decrypt a cert store file; return content as string."""
    safe_path = _check_path_under_roots(path, [Path(settings.cert_store_path)])
    data = safe_path.read_bytes()
    return decrypt(data).decode("utf-8")


def read_cert_store_bytes(path: Path) -> bytes:
    """Read and decrypt a cert store file as raw bytes."""
    safe_path = _check_path_under_roots(path, [Path(settings.cert_store_path)])
    return decrypt(safe_path.read_bytes())


def write_cert_store_bytes(path: Path, content: bytes) -> None:
    """Encrypt raw bytes and write them to path (creating parent directories)."""
    safe_path = _check_path_under_roots(path, [Path(settings.cert_store_path)])
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    safe_path.write_bytes(encrypt(content))
    if safe_path.suffix == ".key":
        try:
            safe_path.chmod(0o600)
        except OSError:
            pass


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
