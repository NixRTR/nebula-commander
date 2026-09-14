"""
One-time fix-up for existing deployments: re-sign certificates for nodes that already
had subnet-router / exit-node routes saved (Node.unsafe_routes) *before* the cert
`-subnets` claim and via-based route propagation to peers were added. Those nodes'
certs don't yet carry the claim other nodes' `tun.unsafe_routes[].via` requires, so
peers can't route to them even though the DB already has the routes.

Not needed for routes added after upgrading - saving unsafe_routes through the API now
triggers a resign automatically (see backend/api/nodes.py::update_node).

Usage (same environment/config as the running app):
  python -m backend.scripts.resign_unsafe_route_certs
"""
import asyncio
import sys

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import Network, Node
from backend.services.cert_manager import CertManager


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Node))
        nodes = [
            n for n in result.scalars().all()
            if n.unsafe_routes and n.public_key and n.ip_address
        ]
        if not nodes:
            print("No nodes with unsafe_routes and an existing certificate found. Nothing to do.")
            return

        cert_manager = CertManager(session)
        resigned = 0
        for node in nodes:
            net_result = await session.execute(select(Network).where(Network.id == node.network_id))
            network = net_result.scalar_one_or_none()
            if not network:
                print(f"Skipping node {node.hostname} (id={node.id}): network not found", file=sys.stderr)
                continue
            try:
                await cert_manager.resign_host_certificate(node, network)
                print(f"Re-signed {node.hostname} (id={node.id}, network={network.name})")
                resigned += 1
            except ValueError as e:
                print(f"Skipping node {node.hostname} (id={node.id}): {e}", file=sys.stderr)

        await session.commit()
        print(f"Done: {resigned} certificate(s) re-signed.")
        print("Affected nodes pick up the corrected certificate and unsafe_routes on their next config poll.")


if __name__ == "__main__":
    asyncio.run(main())
