"""
IP allocation for Nebula networks. CIDR-based allocation with persistence.
"""
import ipaddress
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AllocatedIP, Network

logger = logging.getLogger(__name__)


class IPAllocator:
    """Allocate IPs from a network subnet, avoiding already-allocated IPs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _expire_quarantines(self, network_id: int) -> None:
        """Free addresses whose quarantine is over: the old certificate claiming them has
        expired, so nothing else can present that IP any more."""
        await self.session.execute(
            delete(AllocatedIP).where(
                AllocatedIP.network_id == network_id,
                AllocatedIP.quarantined_until.is_not(None),
                AllocatedIP.quarantined_until <= datetime.utcnow(),
            )
        )

    async def allocate(
        self,
        network_id: int,
        subnet_cidr: str,
        suggested_ip: Optional[str] = None,
        node_id: Optional[int] = None,
    ) -> str:
        """
        Allocate an IP from the subnet. If suggested_ip is valid and free, use it.
        Otherwise pick the next available host IP.

        Quarantined addresses (released by revoke/delete/re-enroll while the old
        certificate is still valid) are never given to another node. node_id may
        reclaim its OWN quarantined address - its old certificate is blocklisted, so
        there's no conflict - and does so first, so a re-enrolled node keeps its IP.
        """
        await self._expire_quarantines(network_id)
        if node_id is not None:
            own = await self.session.scalar(
                select(AllocatedIP).where(
                    AllocatedIP.network_id == network_id,
                    AllocatedIP.node_id == node_id,
                    AllocatedIP.quarantined_until.is_not(None),
                )
            )
            if own is not None and (not suggested_ip or suggested_ip == own.ip_address):
                own.quarantined_until = None
                await self.session.flush()
                return own.ip_address

        net = ipaddress.ip_network(subnet_cidr, strict=False)
        # Skip network and broadcast
        hosts = list(net.hosts())

        if suggested_ip:
            try:
                ip = ipaddress.ip_address(suggested_ip)
                if ip in net and ip not in (net.network_address, net.broadcast_address):
                    # Check if already allocated
                    existing = await self.session.execute(
                        select(AllocatedIP).where(
                            AllocatedIP.network_id == network_id,
                            AllocatedIP.ip_address == suggested_ip,
                        )
                    )
                    if existing.scalar_one_or_none() is None:
                        alloc = AllocatedIP(
                            network_id=network_id,
                            ip_address=suggested_ip,
                            node_id=node_id,
                        )
                        self.session.add(alloc)
                        await self.session.flush()
                        return suggested_ip
                    # Fall through to auto-allocate
            except ValueError:
                pass

        # Allocate first free host IP
        result = await self.session.execute(
            select(AllocatedIP.ip_address).where(AllocatedIP.network_id == network_id)
        )
        used = {row[0] for row in result.fetchall()}

        for ip in hosts:
            addr = str(ip)
            if addr not in used:
                alloc = AllocatedIP(
                    network_id=network_id,
                    ip_address=addr,
                    node_id=node_id,
                )
                self.session.add(alloc)
                await self.session.flush()
                return addr

        quarantined = await self.session.scalar(
            select(AllocatedIP.id).where(
                AllocatedIP.network_id == network_id,
                AllocatedIP.quarantined_until.is_not(None),
            ).limit(1)
        )
        if quarantined is not None:
            raise ValueError(
                f"No free IP in subnet {subnet_cidr} (some addresses are held until the "
                "certificates of revoked or deleted nodes expire)"
            )
        raise ValueError(f"No free IP in subnet {subnet_cidr}")

    async def release(
        self,
        network_id: int,
        ip_address: str,
        quarantine_until: Optional[datetime] = None,
        node_id: Optional[int] = None,
    ) -> None:
        """Release an allocated IP.

        With quarantine_until (the expiry of the certificate that still claims this IP),
        the address is held instead of freed: only node_id may reclaim it before then.
        Pass node_id=None for a deleted node so nobody can.
        """
        result = await self.session.execute(
            select(AllocatedIP).where(
                AllocatedIP.network_id == network_id,
                AllocatedIP.ip_address == ip_address,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            if quarantine_until is None or quarantine_until <= datetime.utcnow():
                return
            row = AllocatedIP(network_id=network_id, ip_address=ip_address)
            self.session.add(row)
        if quarantine_until is not None and quarantine_until > datetime.utcnow():
            row.quarantined_until = quarantine_until
            row.node_id = node_id
        else:
            await self.session.delete(row)
        await self.session.flush()

    async def is_quarantined(self, network_id: int, ip_address: str) -> bool:
        """True if the IP is held because a revoked/deleted node's certificate for it
        hasn't expired yet."""
        await self._expire_quarantines(network_id)
        row = await self.session.scalar(
            select(AllocatedIP.id).where(
                AllocatedIP.network_id == network_id,
                AllocatedIP.ip_address == ip_address,
                AllocatedIP.quarantined_until.is_not(None),
            )
        )
        return row is not None

    async def is_allocated(self, network_id: int, ip_address: str) -> bool:
        """Return True if the IP is already allocated (or still quarantined) in this network."""
        await self._expire_quarantines(network_id)
        result = await self.session.execute(
            select(AllocatedIP).where(
                AllocatedIP.network_id == network_id,
                AllocatedIP.ip_address == ip_address,
            )
        )
        return result.scalar_one_or_none() is not None
