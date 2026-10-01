"""
Certificate revocation that Nebula actually enforces.

Nebula has no revocation of its own beyond expiry: a still-valid host certificate is
only rejected by peers that list its fingerprint in their pki.blocklist. So whenever a
host certificate stops being the node's current one - revoke, delete, re-enroll, or a
re-sign that replaces it (e.g. after a group change, so a removed group's firewall
access really goes away) - its fingerprint is recorded here, and
config_generator puts every unexpired entry into the config of every node in the
network (with pki.disconnect_invalid so live tunnels using it are dropped too).

Entries expire with the certificate itself (its notAfter): once Nebula would reject
the certificate anyway, the entry is pruned so blocklists don't grow forever.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import BlockedCertificate
from ..utils.nebula_cert import _check_path_under_roots, cert_info
from .cert_store import read_cert_store_file

logger = logging.getLogger(__name__)

__all__ = ["block_cert_pem", "block_host_cert_file", "unblock_issued_cert", "host_cert_path", "active_blocklist"]


def host_cert_path(network_id: int, hostname: str) -> Path:
    """Where a host's current certificate lives in the cert store."""
    root = Path(settings.cert_store_path)
    path = root / str(network_id) / "hosts" / f"{hostname}.crt"
    _check_path_under_roots(path, [root])
    return path


async def block_cert_pem(
    session: AsyncSession,
    network_id: int,
    cert_pem: str,
    reason: str,
    node_id: Optional[int] = None,
    hostname: Optional[str] = None,
) -> Optional[datetime]:
    """Add a certificate to the network's blocklist. Returns its notAfter (naive UTC),
    or None if the PEM couldn't be parsed - logged, never raised, so a damaged cert
    file can't block the revoke/delete that's trying to get rid of it."""
    try:
        fingerprint, not_after = cert_info(cert_pem)
    except Exception as e:
        logger.warning("Could not fingerprint %s certificate of %s for the blocklist: %s", reason, hostname, e)
        return None
    if not_after <= datetime.utcnow():
        return not_after  # already expired: Nebula rejects it without a blocklist entry
    existing = await session.scalar(
        select(BlockedCertificate).where(
            BlockedCertificate.network_id == network_id,
            BlockedCertificate.fingerprint == fingerprint,
        )
    )
    if existing is None:
        session.add(
            BlockedCertificate(
                network_id=network_id,
                fingerprint=fingerprint,
                expires_at=not_after,
                reason=reason,
                node_id=node_id,
                hostname=hostname,
            )
        )
        await session.flush()
        logger.info("Blocklisted %s certificate of %s (%s, until %s)", reason, hostname, fingerprint[:16], not_after)
    return not_after


async def block_host_cert_file(
    session: AsyncSession,
    network_id: int,
    hostname: str,
    reason: str,
    node_id: Optional[int] = None,
) -> Optional[datetime]:
    """Blocklist the host certificate currently on disk for this host, if any - call it
    right before the file is deleted or overwritten. Returns the cert's notAfter, or
    None when there was no (parseable) certificate."""
    path = host_cert_path(network_id, hostname)
    if not path.exists():
        return None
    try:
        cert_pem = read_cert_store_file(path)
    except Exception as e:
        logger.warning("Could not read certificate %s for the blocklist: %s", path, e)
        return None
    return await block_cert_pem(session, network_id, cert_pem, reason, node_id=node_id, hostname=hostname)


async def unblock_issued_cert(session: AsyncSession, network_id: int, cert_pem: str) -> None:
    """Make sure a certificate that was just issued as a node's CURRENT one isn't on the
    blocklist. Re-signing back to identical contents within the same second (same key,
    name, IP, groups - timestamps have second precision) yields a byte-identical cert
    with the fingerprint that was just blocklisted as superseded; left alone, the node
    would be cut off by its own current certificate."""
    try:
        fingerprint, _ = cert_info(cert_pem)
    except Exception as e:
        logger.warning("Could not fingerprint newly issued certificate: %s", e)
        return
    await session.execute(
        delete(BlockedCertificate).where(
            BlockedCertificate.network_id == network_id,
            BlockedCertificate.fingerprint == fingerprint,
        )
    )


async def active_blocklist(session: AsyncSession, network_id: int) -> list[str]:
    """Fingerprints every node in the network must reject (sorted, so configs - and
    their ETags - only change when the set does). Prunes entries whose certificate has
    expired."""
    now = datetime.utcnow()
    await session.execute(delete(BlockedCertificate).where(BlockedCertificate.expires_at <= now))
    rows = await session.scalars(
        select(BlockedCertificate.fingerprint).where(BlockedCertificate.network_id == network_id)
    )
    return sorted(set(rows.all()))
