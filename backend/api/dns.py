"""DNS configuration API for per-network dnsmasq zones."""
from typing import List, Optional
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, constr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.oidc import require_user, require_device_token, UserInfo
from ..auth.permissions import check_network_permission
from ..database import get_session
from ..models import (
    Network,
    NetworkDNSAlias,
    NetworkDNSConfig,
    Node,
    User,
)
from ..services.audit import get_client_ip, log_audit


router = APIRouter(prefix="/api/networks/{network_id}/dns", tags=["dns"])


# Pydantic v2 uses `pattern` instead of `regex` for constrained strings.
HostnameLabel = constr(pattern=r"^[a-zA-Z0-9-]+$")


class DNSConfigResponse(BaseModel):
    domain: str
    enabled: bool
    upstream_servers: List[str] = []

    class Config:
        from_attributes = True


class DNSConfigUpdate(BaseModel):
    """domain defaults to network name when creating a new config if omitted."""
    domain: Optional[HostnameLabel | str] = None
    enabled: Optional[bool] = None
    upstream_servers: Optional[List[str]] = None


class DNSAliasResponse(BaseModel):
    id: int
    alias: str
    node_id: int
    node_hostname: str

    class Config:
        from_attributes = True


class DNSAliasCreate(BaseModel):
    alias: HostnameLabel
    node_id: int


class DNSAliasUpdate(BaseModel):
    alias: Optional[HostnameLabel] = None
    node_id: Optional[int] = None


async def _require_owner(
    user: UserInfo,
    network_id: int,
    session: AsyncSession,
) -> User:
    """Ensure caller is network owner; return DB user."""
    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")

    has_permission = await check_network_permission(
        db_user.id,
        network_id,
        "owner",
        session,
    )
    if not has_permission and user.system_role != "system-admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only network owners can manage DNS for this network",
        )
    return db_user


@router.get("", response_model=DNSConfigResponse)
async def get_dns_config(
    network_id: int,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Network).where(Network.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")

    cfg_result = await session.execute(
        select(NetworkDNSConfig).where(NetworkDNSConfig.network_id == network_id)
    )
    cfg = cfg_result.scalar_one_or_none()
    if not cfg:
        # Default DNS config for networks created before we added creation at network create
        cfg = NetworkDNSConfig(
            network_id=network_id,
            domain=network.name,
            enabled=False,
            upstream_servers=None,
        )
        session.add(cfg)
        await session.flush()
        await session.refresh(cfg)

    return DNSConfigResponse(
        domain=cfg.domain,
        enabled=cfg.enabled,
        upstream_servers=cfg.upstream_servers if cfg.upstream_servers is not None else [],
    )


@router.put("", response_model=DNSConfigResponse)
async def upsert_dns_config(
    network_id: int,
    body: DNSConfigUpdate,
    request: Request,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Network).where(Network.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")

    db_user = await _require_owner(user, network_id, session)

    cfg_result = await session.execute(
        select(NetworkDNSConfig).where(NetworkDNSConfig.network_id == network_id)
    )
    cfg = cfg_result.scalar_one_or_none()
    if cfg:
        if body.domain is not None:
            cfg.domain = body.domain.strip()
        if body.enabled is not None:
            cfg.enabled = body.enabled
        if body.upstream_servers is not None:
            cfg.upstream_servers = body.upstream_servers
    else:
        domain = (body.domain.strip() if body.domain and str(body.domain).strip() else network.name)
        cfg = NetworkDNSConfig(
            network_id=network_id,
            domain=domain,
            enabled=body.enabled if body.enabled is not None else True,
            upstream_servers=body.upstream_servers if body.upstream_servers is not None else [],
        )
        session.add(cfg)

    await session.flush()
    await session.refresh(cfg)

    await log_audit(
        session,
        "network_dns_config_updated",
        resource_type="network",
        resource_id=network_id,
        actor_user_id=db_user.id,
        actor_identifier=db_user.email or user.sub,
        client_ip=get_client_ip(request),
        details={"domain": cfg.domain, "enabled": cfg.enabled},
    )

    return DNSConfigResponse(
        domain=cfg.domain,
        enabled=cfg.enabled,
        upstream_servers=cfg.upstream_servers if cfg.upstream_servers is not None else [],
    )


@router.get("/aliases", response_model=List[DNSAliasResponse])
async def list_aliases(
    network_id: int,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Network).where(Network.id == network_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Network not found")

    user_result = await session.execute(select(User).where(User.oidc_sub == user.sub))
    db_user = user_result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")

    await _require_owner(user, network_id, session)

    rows_result = await session.execute(
        select(NetworkDNSAlias, Node)
        .join(Node, NetworkDNSAlias.node_id == Node.id)
        .where(NetworkDNSAlias.network_id == network_id)
    )
    items: list[DNSAliasResponse] = []
    for alias_row, node in rows_result.all():
        items.append(
            DNSAliasResponse(
                id=alias_row.id,
                alias=alias_row.alias,
                node_id=alias_row.node_id,
                node_hostname=node.hostname,
            )
        )
    return items


@router.post("/aliases", response_model=DNSAliasResponse, status_code=status.HTTP_201_CREATED)
async def create_alias(
    network_id: int,
    body: DNSAliasCreate,
    request: Request,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Network).where(Network.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")

    db_user = await _require_owner(user, network_id, session)

    node_result = await session.execute(
        select(Node).where(Node.id == body.node_id, Node.network_id == network_id)
    )
    node = node_result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found in this network")

    existing = await session.execute(
        select(NetworkDNSAlias).where(
            NetworkDNSAlias.network_id == network_id,
            NetworkDNSAlias.alias == body.alias,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Alias already exists for this network",
        )

    alias = NetworkDNSAlias(
        network_id=network_id,
        node_id=node.id,
        alias=body.alias,
    )
    session.add(alias)
    await session.flush()
    await session.refresh(alias)

    await log_audit(
        session,
        "network_dns_alias_created",
        resource_type="network",
        resource_id=network_id,
        actor_user_id=db_user.id,
        actor_identifier=db_user.email or user.sub,
        client_ip=get_client_ip(request),
        details={"alias": alias.alias, "node_id": alias.node_id},
    )

    return DNSAliasResponse(
        id=alias.id,
        alias=alias.alias,
        node_id=alias.node_id,
        node_hostname=node.hostname,
    )


@router.delete("/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alias(
    network_id: int,
    alias_id: int,
    request: Request,
    user: UserInfo = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Network).where(Network.id == network_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Network not found")

    db_user = await _require_owner(user, network_id, session)

    alias_result = await session.execute(
        select(NetworkDNSAlias).where(
            NetworkDNSAlias.id == alias_id,
            NetworkDNSAlias.network_id == network_id,
        )
    )
    alias = alias_result.scalar_one_or_none()
    if not alias:
        raise HTTPException(status_code=404, detail="Alias not found")

    await session.delete(alias)
    await session.flush()

    await log_audit(
        session,
        "network_dns_alias_deleted",
        resource_type="network",
        resource_id=network_id,
        actor_user_id=db_user.id,
        actor_identifier=db_user.email or user.sub,
        client_ip=get_client_ip(request),
        details={"alias_id": alias_id},
    )
    return None


def _build_dnsmasq_config(
    domain: str,
    nodes: list[Node],
    aliases: list[NetworkDNSAlias],
    upstream_servers: Optional[List[str]] = None,
    listen_ip: Optional[str] = None,
) -> str:
    """Build dnsmasq config. Local zone (domain, local=, address=, host-record=) before server=
    so the zone is answered from config; upstream server= last (per nixos-router and dnsmasq docs).
    """
    lines: list[str] = []
    if listen_ip:
        lines.append(f"listen-address={listen_ip}")
    lines.append("bind-interfaces")
    lines.append("port=53")
    lines.append("no-resolv")
    lines.append("no-poll")
    # Avoid serving cached NXDOMAIN from earlier upstream lookups
    lines.append("no-negcache")
    lines.append("cache-size=0")
    # All local data from config only; do not use /etc/hosts (avoids conflicts)
    lines.append("no-hosts")
    # Never-forward zone; define before address= and host-record= (nixos-router pattern)
    # (omit domain= to avoid any interaction with host-record matching)
    lines.append(f"local=/{domain}/")
    lines.append("")
    # Fallback IP for the domain (first node with an IP); address= makes *.domain resolve
    fallback_ip = None
    for n in nodes:
        if n.ip_address:
            fallback_ip = n.ip_address
            break
    if fallback_ip:
        lines.append(f"address=/{domain}/{fallback_ip}")
        lines.append(f"host-record={domain},{fallback_ip}")
    for n in nodes:
        if not n.hostname or not n.ip_address:
            continue
        fqdn = f"{n.hostname}.{domain}"
        lines.append(f"host-record={fqdn},{n.ip_address}")
    node_by_id = {n.id: n for n in nodes}
    for a in aliases:
        node = node_by_id.get(a.node_id)
        if not node or not node.hostname or not node.ip_address:
            continue
        fqdn = f"{a.alias}.{domain}"
        lines.append(f"host-record={fqdn},{node.ip_address}")
    lines.append("")
    # Upstream servers last: used only for queries not in our local zone
    for s in upstream_servers or []:
        s = (s or "").strip()
        if s:
            lines.append(f"server={s}")
    return "\n".join(lines)


@router.get("/dnsmasq.conf")
async def get_dnsmasq_config(
    network_id: int,
    request: Request,
    node_id: int = Depends(require_device_token),
    session: AsyncSession = Depends(get_session),
):
    """
    Device-facing endpoint that returns dnsmasq config for this network.
    Requires device Bearer token; the requesting node's Nebula IP is used as listen-address.
    """
    result = await session.execute(select(Network).where(Network.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")

    node_result = await session.execute(select(Node).where(Node.id == node_id))
    node = node_result.scalar_one_or_none()
    if not node or node.network_id != network_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is not part of this network",
        )
    if not node.ip_address:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Node has no Nebula IP yet; DNS config will be available after the node is assigned an IP",
        )

    cfg_result = await session.execute(
        select(NetworkDNSConfig).where(NetworkDNSConfig.network_id == network_id)
    )
    cfg = cfg_result.scalar_one_or_none()
    if not cfg or not cfg.enabled:
        raise HTTPException(status_code=404, detail="DNS not enabled for this network")

    nodes_result = await session.execute(
        select(Node).where(Node.network_id == network_id)
    )
    nodes = nodes_result.scalars().all()

    aliases_result = await session.execute(
        select(NetworkDNSAlias).where(NetworkDNSAlias.network_id == network_id)
    )
    aliases = aliases_result.scalars().all()

    body = _build_dnsmasq_config(
        cfg.domain,
        nodes,
        aliases,
        upstream_servers=cfg.upstream_servers if cfg.upstream_servers is not None else [],
        listen_ip=node.ip_address,
    )
    etag = hashlib.sha256(body.encode("utf-8")).hexdigest()

    if_match = request.headers.get("If-None-Match")
    if if_match and if_match.strip('"') == etag:
        return PlainTextResponse(status_code=status.HTTP_304_NOT_MODIFIED, content="")

    response = PlainTextResponse(content=body)
    response.headers["ETag"] = f'"{etag}"'
    return response

