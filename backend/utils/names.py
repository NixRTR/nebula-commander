"""
Names that end up inside nebula-cert arguments or cert store paths.

Node names become file names (cert_store/<network>/hosts/<name>.crt) and the cert's
-name; group names go into -groups, which nebula-cert splits on commas - so a group
called "web,admin" would sign a cert carrying both groups while the UI shows one.
"""
import re
from typing import Optional

# A DNS-style label set: usable as one path segment and as one -groups item.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
_NAME_RULE = "1-63 characters of letters, digits, '.', '_' or '-', starting with a letter or digit"


def validate_node_name(name: str) -> str:
    """Strip and validate a node name supplied by a client; raises ValueError."""
    name = (name or "").strip()
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"Node name must be {_NAME_RULE}")
    return name


def validate_group_name(name: Optional[str]) -> Optional[str]:
    """Strip and validate a group name; None/blank pass through (= no group)."""
    if name is None or not name.strip():
        return name
    name = name.strip()
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"Group name must be {_NAME_RULE}")
    return name


def ca_name(network_name: str, network_id: int) -> str:
    """The network's name as a nebula-cert CA -name: display names may hold spaces or
    non-ASCII, which nebula_cert's argument allowlist rejects. It's only a label in the CA."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", network_name or "").strip("-.")[:63]
    return safe or f"network-{network_id}"
