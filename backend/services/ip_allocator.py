"""
IP allocation for Nebula networks. CIDR-based allocation with persistence.
"""
import ipaddress
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AllocatedIP, Network

logger = logging.getLogger(__name__)


class IPAllocator:
    """Allocate IPs from a network subnet, avoiding already-allocated IPs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def allocate(
        self,
        network_id: int,
        subnet_cidr: str,
        suggested_ip: Optional[str] = None,
    ) -> str:
        """
        Allocate an IP from the subnet. If suggested_ip is valid and free, use it.
        Otherwise pick the next available host IP.
        """
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
                )
                self.session.add(alloc)
                await self.session.flush()
                return addr

        raise ValueError(f"No free IP in subnet {subnet_cidr}")

    async def release(self, network_id: int, ip_address: str) -> None:
        """Release an allocated IP."""
        result = await self.session.execute(
            select(AllocatedIP).where(
                AllocatedIP.network_id == network_id,
                AllocatedIP.ip_address == ip_address,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            await self.session.delete(row)
            await self.session.flush()

    async def is_allocated(self, network_id: int, ip_address: str) -> bool:
        """Return True if the IP is already allocated in this network."""
        result = await self.session.execute(
            select(AllocatedIP).where(
                AllocatedIP.network_id == network_id,
                AllocatedIP.ip_address == ip_address,
            )
        )
        return result.scalar_one_or_none() is not None
