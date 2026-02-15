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
    UniqueConstraint,
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
    firewall_outbound_action: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # drop | reject
    firewall_inbound_action: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    firewall_outbound_rules: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    firewall_inbound_rules: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    nodes: Mapped[list["Node"]] = relationship("Node", back_populates="network")
    allocated_ips: Mapped[list["AllocatedIP"]] = relationship(
        "AllocatedIP", back_populates="network"
    )
    group_firewalls: Mapped[list["NetworkGroupFirewall"]] = relationship(
        "NetworkGroupFirewall", back_populates="network", cascade="all, delete-orphan"
    )
    permissions: Mapped[list["NetworkPermission"]] = relationship(
        "NetworkPermission", back_populates="network"
    )
    settings: Mapped[Optional["NetworkSettings"]] = relationship(
        "NetworkSettings", back_populates="network", uselist=False
    )
    node_requests: Mapped[list["NodeRequest"]] = relationship(
        "NodeRequest", back_populates="network"
    )


class NetworkGroupFirewall(Base):
    """Per-group firewall rules for a network. Keyed by (network_id, group_name)."""

    __tablename__ = "network_group_firewall"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id"), nullable=False)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    outbound_rules: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    inbound_rules: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    network: Mapped["Network"] = relationship("Network", back_populates="group_firewalls")

    __table_args__ = (
        UniqueConstraint("network_id", "group_name", name="uq_network_group_firewall_network_group"),
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
    is_relay: Mapped[bool] = mapped_column(Boolean, default=False)
    public_endpoint: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # e.g. hostname:4242 for static_host_map
    lighthouse_options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # serve_dns, dns_host, dns_port, interval_seconds
    logging_options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # level, format, disable_timestamp, timestamp_format
    punchy_options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # respond, delay, respond_delay
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
    permissions: Mapped[list["NodePermission"]] = relationship(
        "NodePermission", back_populates="node"
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
    role: Mapped[str] = mapped_column(String(64), default="user")  # admin, user, viewer (legacy)
    system_role: Mapped[str] = mapped_column(String(64), default="user")  # system-admin, network-owner, user
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    network_permissions: Mapped[list["NetworkPermission"]] = relationship(
        "NetworkPermission", back_populates="user", foreign_keys="NetworkPermission.user_id"
    )
    node_permissions: Mapped[list["NodePermission"]] = relationship(
        "NodePermission", back_populates="user", foreign_keys="NodePermission.user_id"
    )
    node_requests: Mapped[list["NodeRequest"]] = relationship(
        "NodeRequest", back_populates="requested_by_user", foreign_keys="NodeRequest.requested_by_user_id"
    )
    granted_access: Mapped[list["AccessGrant"]] = relationship(
        "AccessGrant", back_populates="admin_user", foreign_keys="AccessGrant.admin_user_id"
    )


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


class NetworkPermission(Base):
    """User permissions for a network."""

    __tablename__ = "network_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # owner, member
    can_manage_nodes: Mapped[bool] = mapped_column(Boolean, default=False)
    can_invite_users: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_firewall: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    invited_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="network_permissions", foreign_keys=[user_id])
    network: Mapped["Network"] = relationship("Network", back_populates="permissions")
    invited_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[invited_by_user_id])

    __table_args__ = (
        UniqueConstraint("user_id", "network_id", name="uq_network_permission_user_network"),
    )


class NodePermission(Base):
    """User permissions for a specific node."""

    __tablename__ = "node_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    can_view_details: Mapped[bool] = mapped_column(Boolean, default=True)
    can_download_config: Mapped[bool] = mapped_column(Boolean, default=True)
    can_download_cert: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    granted_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="node_permissions", foreign_keys=[user_id])
    node: Mapped["Node"] = relationship("Node", back_populates="permissions")
    granted_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[granted_by_user_id])

    __table_args__ = (
        UniqueConstraint("user_id", "node_id", name="uq_node_permission_user_node"),
    )


class NodeRequest(Base):
    """Node creation request from a user."""

    __tablename__ = "node_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id"), nullable=False)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    groups: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    is_lighthouse: Mapped[bool] = mapped_column(Boolean, default=False)
    is_relay: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, approved, rejected
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_node_id: Mapped[Optional[int]] = mapped_column(ForeignKey("nodes.id"), nullable=True)

    network: Mapped["Network"] = relationship("Network", back_populates="node_requests")
    requested_by_user: Mapped["User"] = relationship("User", back_populates="node_requests", foreign_keys=[requested_by_user_id])
    approved_by_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[approved_by_user_id])
    created_node: Mapped[Optional["Node"]] = relationship("Node", foreign_keys=[created_node_id])


class AccessGrant(Base):
    """Temporary system admin access to a resource."""

    __tablename__ = "access_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)  # network, node
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    granted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    admin_user: Mapped["User"] = relationship("User", back_populates="granted_access", foreign_keys=[admin_user_id])
    granted_by_user: Mapped["User"] = relationship("User", foreign_keys=[granted_by_user_id])


class NetworkSettings(Base):
    """Per-network configuration settings."""

    __tablename__ = "network_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id"), unique=True, nullable=False)
    auto_approve_nodes: Mapped[bool] = mapped_column(Boolean, default=False)
    default_node_groups: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    default_is_lighthouse: Mapped[bool] = mapped_column(Boolean, default=False)
    default_is_relay: Mapped[bool] = mapped_column(Boolean, default=False)

    network: Mapped["Network"] = relationship("Network", back_populates="settings")


class Invitation(Base):
    """User invitation to join a network."""

    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id"), nullable=False)
    invited_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # owner, member
    can_manage_nodes: Mapped[bool] = mapped_column(Boolean, default=False)
    can_invite_users: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_firewall: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, accepted, expired, revoked
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    email_status: Mapped[str] = mapped_column(String(32), default="not_sent")  # not_sent, sending, sent, failed
    email_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    email_error: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    network: Mapped["Network"] = relationship("Network")
    invited_by_user: Mapped["User"] = relationship("User", foreign_keys=[invited_by_user_id])
