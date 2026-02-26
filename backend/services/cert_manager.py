"""
Certificate management: CA creation, signing with betterkeys (client public key),
and full certificate creation (server-generated keypair).
"""
import tempfile
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Network, Node, Certificate, AllocatedIP
from ..utils.nebula_cert import ca_generate, cert_sign, keygen
from .cert_store import read_cert_store_file, write_cert_store_file
from .ip_allocator import IPAllocator

logger = logging.getLogger(__name__)


class CertManager:
    """Issue and manage Nebula certificates with betterkeys and IP allocation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ip_allocator = IPAllocator(session)

    async def ensure_ca(self, network: Network) -> None:
        """Create CA for the network if not already present."""
        if network.ca_cert_path and Path(network.ca_cert_path).exists():
            return
        base = Path(settings.cert_store_path) / str(network.id)
        base.mkdir(parents=True, exist_ok=True)
        ca_crt = base / "ca.crt"
        ca_key = base / "ca.key"
        # nebula-cert refuses to overwrite existing CA files; use them if present (e.g. volume persisted, DB reset)
        if ca_crt.exists() and ca_key.exists():
            network.ca_cert_path = str(ca_crt)
            network.ca_key_path = str(ca_key)
            await self.session.flush()
            return
        ca_generate(network.name, ca_crt, ca_key)
        # Overwrite with encrypted storage
        write_cert_store_file(ca_crt, ca_crt.read_text())
        write_cert_store_file(ca_key, ca_key.read_text())
        network.ca_cert_path = str(ca_crt)
        network.ca_key_path = str(ca_key)
        await self.session.flush()

    async def sign_host(
        self,
        network: Network,
        name: str,
        public_key_pem: str,
        groups: Optional[list[str]] = None,
        suggested_ip: Optional[str] = None,
        duration_days: Optional[int] = None,
    ) -> tuple[str, str]:
        """
        Sign a host certificate (betterkeys: client sends only public key).
        Returns (ip_address, cert_pem).
        """
        await self.ensure_ca(network)
        duration_days = duration_days or settings.default_cert_expiry_days
        duration_hours = duration_days * 24

        ip = await self.ip_allocator.allocate(
            network.id, network.subnet_cidr, suggested_ip
        )

        base = Path(settings.cert_store_path) / str(network.id) / "hosts"
        base.mkdir(parents=True, exist_ok=True)
        out_crt = base / f"{name}.crt"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pub", delete=False
        ) as f:
            f.write(public_key_pem)
            pub_path = Path(f.name)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                ca_crt_tmp = tmp / "ca.crt"
                ca_key_tmp = tmp / "ca.key"
                ca_crt_tmp.write_text(read_cert_store_file(Path(network.ca_cert_path)))
                ca_key_tmp.write_text(read_cert_store_file(Path(network.ca_key_path)))
                cert_sign(
                    ca_crt_tmp,
                    ca_key_tmp,
                    name=name,
                    ip=ip,
                    out_crt=out_crt,
                    groups=groups or [],
                    duration_hours=duration_hours,
                    in_pub=pub_path,
                    subnet_cidr=network.subnet_cidr,
                )
            cert_pem = out_crt.read_text()
            write_cert_store_file(out_crt, cert_pem)
        finally:
            pub_path.unlink(missing_ok=True)

        return ip, cert_pem

    async def create_host_certificate(
        self,
        network: Network,
        name: str,
        groups: Optional[list[str]] = None,
        suggested_ip: Optional[str] = None,
        duration_days: Optional[int] = None,
    ) -> tuple[str, str, str, str, str]:
        """
        Create a host certificate by generating a keypair on the server, signing it,
        and returning (ip_address, cert_pem, private_key_pem, ca_pem, public_key_pem).
        The private key is also stored on the server and served in the device bundle
        and node certs zip; it is still returned once in the API response.
        """
        await self.ensure_ca(network)
        duration_days = duration_days or settings.default_cert_expiry_days
        duration_hours = duration_days * 24

        ip = await self.ip_allocator.allocate(
            network.id, network.subnet_cidr, suggested_ip
        )

        base = Path(settings.cert_store_path) / str(network.id) / "hosts"
        base.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pub_path = tmp / "host.pub"
            key_path = tmp / "host.key"
            out_crt_tmp = tmp / "host.crt"
            ca_crt_tmp = tmp / "ca.crt"
            ca_key_tmp = tmp / "ca.key"
            ca_crt_tmp.write_text(read_cert_store_file(Path(network.ca_cert_path)))
            ca_key_tmp.write_text(read_cert_store_file(Path(network.ca_key_path)))
            keygen(out_pub=pub_path, out_key=key_path)
            cert_sign(
                ca_crt_tmp,
                ca_key_tmp,
                name=name,
                ip=ip,
                out_crt=out_crt_tmp,
                groups=groups or [],
                duration_hours=duration_hours,
                in_pub=pub_path,
                subnet_cidr=network.subnet_cidr,
            )
            cert_pem = out_crt_tmp.read_text()
            private_key_pem = key_path.read_text()
            public_key_pem = pub_path.read_text()

        # Persist encrypted
        write_cert_store_file(base / f"{name}.crt", cert_pem)
        key_file = base / f"{name}.key"
        write_cert_store_file(key_file, private_key_pem)

        ca_pem = ""
        if network.ca_cert_path:
            try:
                ca_pem = read_cert_store_file(Path(network.ca_cert_path))
            except FileNotFoundError:
                logger.warning("CA cert file not found: %s", network.ca_cert_path)
            except PermissionError:
                logger.error("Permission denied reading CA cert: %s", network.ca_cert_path)
            except Exception as e:
                logger.error("Unexpected error reading CA cert from %s: %s", network.ca_cert_path, e)

        return ip, cert_pem, private_key_pem, ca_pem, public_key_pem

    async def create_host_certificate_for_existing_node(
        self,
        node: Node,
        network: Network,
        suggested_ip: Optional[str] = None,
        duration_days: Optional[int] = None,
    ) -> tuple[str, str, str, str, str]:
        """
        Create a new host certificate for an existing node (e.g. after revoke or re-enroll).
        Allocates IP, generates new keypair, signs, writes files, updates node, adds Certificate record.
        Returns (ip_address, cert_pem, private_key_pem, ca_pem, public_key_pem).
        """
        await self.ensure_ca(network)
        duration_days = duration_days or settings.default_cert_expiry_days
        duration_hours = duration_days * 24

        ip = await self.ip_allocator.allocate(
            network.id, network.subnet_cidr, suggested_ip
        )

        base = Path(settings.cert_store_path) / str(network.id) / "hosts"
        base.mkdir(parents=True, exist_ok=True)
        name = node.hostname

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pub_path = tmp / "host.pub"
            key_path = tmp / "host.key"
            out_crt_tmp = tmp / "host.crt"
            ca_crt_tmp = tmp / "ca.crt"
            ca_key_tmp = tmp / "ca.key"
            ca_crt_tmp.write_text(read_cert_store_file(Path(network.ca_cert_path)))
            ca_key_tmp.write_text(read_cert_store_file(Path(network.ca_key_path)))
            keygen(out_pub=pub_path, out_key=key_path)
            cert_sign(
                ca_crt_tmp,
                ca_key_tmp,
                name=name,
                ip=ip,
                out_crt=out_crt_tmp,
                groups=node.groups or [],
                duration_hours=duration_hours,
                in_pub=pub_path,
                subnet_cidr=network.subnet_cidr,
            )
            cert_pem = out_crt_tmp.read_text()
            private_key_pem = key_path.read_text()
            public_key_pem = pub_path.read_text()

        write_cert_store_file(base / f"{name}.crt", cert_pem)
        key_file = base / f"{name}.key"
        write_cert_store_file(key_file, private_key_pem)

        node.ip_address = ip
        node.public_key = public_key_pem
        node.cert_fingerprint = None  # Can be set when device first polls
        node.status = "active"
        await self.session.flush()

        expires_at = datetime.utcnow() + timedelta(days=duration_days)
        cert_record = Certificate(
            node_id=node.id,
            expires_at=expires_at,
            cert_path=None,
        )
        self.session.add(cert_record)
        await self.session.flush()

        ca_pem = ""
        if network.ca_cert_path:
            try:
                ca_pem = read_cert_store_file(Path(network.ca_cert_path))
            except FileNotFoundError:
                logger.warning("CA cert file not found: %s", network.ca_cert_path)
            except PermissionError:
                logger.error("Permission denied reading CA cert: %s", network.ca_cert_path)
            except Exception as e:
                logger.error("Unexpected error reading CA cert from %s: %s", network.ca_cert_path, e)

        return ip, cert_pem, private_key_pem, ca_pem, public_key_pem
