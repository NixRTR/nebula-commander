"""
SQLAlchemy models for Nebula Commander
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Network(Base):
    """Nebula overlay network."""

    __tablename__ = "networks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    subnet_cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    ca_cert_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    ca_key_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    nodes: Mapped[list["Node"]] = relationship("Node", back_populates="network")
    allocated_ips: Mapped[list["AllocatedIP"]] = relationship(
        "AllocatedIP", back_populates="network"
    )


class Node(Base):
    """Nebula node (host) in a network."""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id"), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    public_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cert_fingerprint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    groups: Mapped[Optional[list]] = mapped_column(JSON, default=list)  # ["group1", "group2"]
    is_lighthouse: Mapped[bool] = mapped_column(Boolean, default=False)
    public_endpoint: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # e.g. hostname:4242 for static_host_map
    lighthouse_options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # serve_dns, dns_host, dns_port, interval_seconds
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, active, revoked, offline
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    first_polled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # set when device first fetches config/bundle
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    network: Mapped["Network"] = relationship("Network", back_populates="nodes")
    certificates: Mapped[list["Certificate"]] = relationship(
        "Certificate", back_populates="node"
    )
    configs: Mapped[list["NetworkConfig"]] = relationship(
        "NetworkConfig", back_populates="node"
    )
    enrollment_codes: Mapped[list["EnrollmentCode"]] = relationship(
        "EnrollmentCode", back_populates="node"
    )


class Certificate(Base):
    """Issued Nebula host certificate."""

    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cert_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    node: Mapped["Node"] = relationship("Node", back_populates="certificates")


class User(Base):
    """OIDC user with permissions."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    oidc_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(64), default="user")  # admin, user, viewer
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NetworkConfig(Base):
    """Generated Nebula config for a node."""

    __tablename__ = "network_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    config_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deployed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    node: Mapped["Node"] = relationship("Node", back_populates="configs")


class EnrollmentCode(Base):
    """One-time enrollment code for a node (dnclient-style)."""

    __tablename__ = "enrollment_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    node: Mapped["Node"] = relationship("Node", back_populates="enrollment_codes")


class AllocatedIP(Base):
    """IP address allocation for a network (tracks used IPs)."""

    __tablename__ = "allocated_ips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id"), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    node_id: Mapped[Optional[int]] = mapped_column(ForeignKey("nodes.id"), nullable=True)

    network: Mapped["Network"] = relationship("Network", back_populates="allocated_ips")
