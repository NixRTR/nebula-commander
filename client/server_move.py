"""
Following a server move (backend/api/move.py) without anyone touching the device.

Each enrolled network pins its server's Ed25519 instance key (enroll reply or
GET /api/device/info) along with that server's registrable domain. While the server is
moving, every device response carries a signed statement (X-Nebula-Commander-Move):

    <base64url(body)>.<base64url(signature)>   body = {"v", "move_id", "old_url",
    "new_url", "new_key_fp", "created_at", "switch_at", "expires_at"}

A network switches only when all of these hold, and otherwise stays where it is and
tries again on a later poll:
  1. the signature is from the pinned key, the statement hasn't expired, and new_url is
     https (http only if the current server is http too);
  2. this host's move_policy (settings.json, never set by a server) allows it:
     "any" (default), "same-domain" or "none";
  3. the wait is over: the later of the statement's switch_at and this device's own
     floor since it first saw the move - 1 h within the same registrable domain, 24 h
     for another domain or an IP, so a compromised server can't rush a device off to
     somewhere else unnoticed;
  4. the statement is still being served (a cancelled move disappears);
  5. the new server signs a fresh nonce with a key whose fingerprint is new_key_fp,
     and knows this device: /api/device/info there answers its token with the same
     node and network.
Then the network's server is rewritten (the previous one is kept) and the new server's
key is pinned; the supervisor restarts the network against it.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.parse import urlparse

MOVE_HEADER = "X-Nebula-Commander-Move"
STATEMENT_VERSION = 1
PROOF_PREFIX = "nc-move-proof-v1"
SAME_DOMAIN_FLOOR = 3600
FOREIGN_FLOOR = 24 * 3600
POLICIES = ("any", "same-domain", "none")
# Between attempts to verify the new server once the wait is over.
RETRY_SECONDS = 300

_SECOND_LEVEL = ("co", "com", "org", "net", "ac", "gov", "edu")


class MoveError(Exception):
    pass


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def fingerprint(public_key_b64: str) -> str:
    raw = base64.b64decode(public_key_b64)
    return "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode("ascii")


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def registrable_domain(host: str) -> Optional[str]:
    """nebulacdr.net for beardedtek.nebulacdr.net, example.co.uk for nc.example.co.uk,
    None for an IP. Same heuristic as backend/api/move.py."""
    host = (host or "").strip().rstrip(".").lower()
    try:
        ipaddress.ip_address(host.strip("[]"))
        return None
    except ValueError:
        pass
    labels = [x for x in host.split(".") if x]
    if len(labels) < 2:
        return host or None
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_domain(pinned_domain: Optional[str], new_url: str) -> bool:
    new = registrable_domain(host_of(new_url))
    return bool(pinned_domain) and new == pinned_domain


def floor_seconds(pinned_domain: Optional[str], new_url: str) -> int:
    """This device's own minimum wait. A dev build (never a release) may shorten it with
    NCCLIENT_MOVE_FLOOR_SECONDS for testing."""
    from client.version import DEV_VERSION, VERSION

    override = os.environ.get("NCCLIENT_MOVE_FLOOR_SECONDS", "").strip()
    if override and VERSION == DEV_VERSION:
        try:
            return max(0, int(override))
        except ValueError:
            pass
    return SAME_DOMAIN_FLOOR if same_domain(pinned_domain, new_url) else FOREIGN_FLOOR


def policy_allows(policy: Optional[str], pinned_domain: Optional[str], new_url: str) -> bool:
    policy = policy if policy in POLICIES else "any"
    if policy == "none":
        return False
    if policy == "same-domain":
        return same_domain(pinned_domain, new_url)
    return True


def _parse_time(value: str) -> float:
    return datetime.fromisoformat(value.rstrip("Z")).replace(tzinfo=timezone.utc).timestamp()


def verify_statement(header: str, pinned_key_b64: Optional[str], current_server: str,
                     now: Optional[float] = None) -> dict:
    """The statement, if it is signed by the pinned key, current and well-formed."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not pinned_key_b64:
        raise MoveError("this network has no pinned server key yet")
    try:
        body_b64, sig_b64 = header.strip().split(".")
        body, sig = _b64url_decode(body_b64), _b64url_decode(sig_b64)
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pinned_key_b64)).verify(sig, body)
    except InvalidSignature:
        raise MoveError("move statement not signed by this server's key")
    except Exception as e:
        raise MoveError(f"unreadable move statement: {e}")
    try:
        stmt = json.loads(body)
        if stmt.get("v") != STATEMENT_VERSION:
            raise MoveError(f"unsupported move statement version {stmt.get('v')!r}")
        for k in ("move_id", "new_url", "new_key_fp", "switch_at", "expires_at"):
            if not isinstance(stmt.get(k), str) or not stmt[k]:
                raise MoveError(f"move statement without {k}")
        stmt["_switch_at"] = _parse_time(stmt["switch_at"])
        stmt["_expires_at"] = _parse_time(stmt["expires_at"])
    except MoveError:
        raise
    except Exception as e:
        raise MoveError(f"unreadable move statement: {e}")
    if (now if now is not None else time.time()) >= stmt["_expires_at"]:
        raise MoveError("move statement has expired")
    new = urlparse(stmt["new_url"])
    current_scheme = urlparse(current_server).scheme or "https"
    if not new.hostname or new.scheme not in ("https", "http") or (new.scheme == "http" and current_scheme != "http"):
        raise MoveError(f"refusing to move to {stmt['new_url']} (https required)")
    if stmt["new_url"].rstrip("/") == current_server.rstrip("/"):
        raise MoveError("move statement points at the current server")
    return stmt


def prove_new_server(new_url: str, token: str, node_id: int, expected_fp: str, timeout: float = 20) -> str:
    """Check the new server holds the key the statement names and recognizes this
    device. Returns its public key (base64) to pin. Raises MoveError."""
    import requests
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    base = new_url.rstrip("/")
    nonce = secrets.token_urlsafe(24)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.post(f"{base}/api/device/move-proof", json={"nonce": nonce, "new_url": base},
                          headers=headers, timeout=timeout, allow_redirects=False)
    except requests.RequestException as e:
        raise MoveError(f"new server unreachable: {e}")
    if r.status_code == 401:
        raise MoveError("new server doesn't recognize this device (was it imported with device keys?)")
    if not r.ok:
        raise MoveError(f"new server answered {r.status_code} to the move proof")
    try:
        data = r.json()
        key_b64, sig = str(data["public_key"]), _b64url_decode(str(data["signature"]))
    except Exception:
        raise MoveError("new server sent an unreadable move proof")
    if fingerprint(key_b64) != expected_fp:
        raise MoveError("new server's key doesn't match the fingerprint in the move statement")
    message = f"{PROOF_PREFIX}|{nonce}|{node_id}|{base}".encode("utf-8")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key_b64)).verify(sig, message)
    except (InvalidSignature, ValueError):
        raise MoveError("new server's move proof signature is invalid")
    return key_b64


def device_info(base: str, token: str, timeout: float = 15) -> dict:
    import requests

    try:
        r = requests.get(f"{base.rstrip('/')}/api/device/info", headers={"Authorization": f"Bearer {token}"},
                         timeout=timeout, allow_redirects=False)
    except requests.RequestException as e:
        raise MoveError(f"{base} unreachable: {e}")
    if not r.ok:
        raise MoveError(f"{base} answered {r.status_code} to /api/device/info")
    return r.json()


class MoveTracker:
    """One network's view of a move, driven by its poll loop (client/ncclient.py)."""

    def __init__(self, enrollment_id: str, debug_log: Optional[Callable[[str], None]] = None):
        self.enrollment_id = enrollment_id
        self.debug_log = debug_log
        self.state: Optional[str] = None  # pending, failed, switching (heartbeat move_state)
        self.error: Optional[str] = None
        self._last_attempt = 0.0
        self._logged: Optional[str] = None
        self._pin_checked = False

    def _log(self, msg: str) -> None:
        if msg != self._logged and self.debug_log:
            self.debug_log(msg)
        self._logged = msg

    def _enrollment(self) -> dict:
        from client.config import find_enrollment, load_settings

        return find_enrollment(load_settings(), self.enrollment_id) or {}

    def _update(self, **fields) -> None:
        from client.service_api import update_enrollment

        update_enrollment(self.enrollment_id, **fields)

    def ready(self) -> bool:
        return bool(self._enrollment().get("instance_key"))

    def pin_if_needed(self, base: str, token: str) -> None:
        """Pin the server's key once (networks enrolled before 0.9.0, or on a server
        that didn't send it at enroll). Never replaces a pinned key."""
        if self._pin_checked or self._enrollment().get("instance_key"):
            return
        try:
            info = device_info(base, token)
        except MoveError as err:
            self._log(f"server move: could not pin the server key yet: {err}")
            return
        self._pin_checked = True
        key = info.get("instance_key")
        if not key:  # a server before 0.9.0: ask again after the next restart
            return
        self._update(instance_key=key, pinned_domain=registrable_domain(host_of(base)),
                     network_id=info.get("network_id"))

    def heartbeat_fields(self) -> dict:
        fields = {"move_ready": self.ready(), "move_state": self.state}
        if self.state == "failed" and self.error:
            fields["move_error"] = self.error[:255]
        return fields

    def notice(self) -> Optional[str]:
        pm = self._enrollment().get("pending_move") or {}
        if not pm.get("new_url"):
            return None
        when = datetime.fromtimestamp(pm.get("earliest") or 0).strftime("%Y-%m-%d %H:%M")
        where = host_of(pm["new_url"]) or pm["new_url"]
        if pm.get("cross_domain"):
            return f"Moving to a different provider: {where} (from {when})"
        return f"Moving to {where} (from {when})"

    def observe(self, header: Optional[str], base: str, token: str, node_id: Optional[int],
                send_switching: Callable[[], None], now: Optional[float] = None) -> Optional[str]:
        """Called with each poll's move header (None when absent). Returns the new server
        URL once the network has switched to it, else None."""
        now = time.time() if now is None else now
        e = self._enrollment()
        pending = e.get("pending_move") if isinstance(e.get("pending_move"), dict) else None
        if not header:
            if pending:
                self._log(f"server move to {pending.get('new_url')} was cancelled")
                self._update(pending_move=None)
            self.state, self.error = None, None
            return None
        try:
            stmt = verify_statement(header, e.get("instance_key"), base, now)
        except MoveError as err:
            self.state, self.error = "failed", str(err)
            self._log(f"server move ignored: {err}")
            return None
        new_url = stmt["new_url"].rstrip("/")
        pinned_domain = e.get("pinned_domain")
        from client.config import load_settings

        if not policy_allows(load_settings().get("move_policy"), pinned_domain, new_url):
            self.state, self.error = "failed", f"move to {new_url} blocked by this device's move_policy"
            self._log(f"server move ignored: {self.error}")
            return None
        if not pending or pending.get("move_id") != stmt["move_id"]:
            earliest = max(stmt["_switch_at"], now + floor_seconds(pinned_domain, new_url))
            pending = {"move_id": stmt["move_id"], "new_url": new_url, "first_seen": now,
                       "earliest": earliest, "cross_domain": not same_domain(pinned_domain, new_url)}
            self._update(pending_move=pending)
            self._log(f"server move to {new_url} announced; switching after "
                      f"{datetime.fromtimestamp(earliest).isoformat(timespec='minutes')}")
        if now < pending["earliest"]:
            self.state, self.error = "pending", None
            return None
        if now - self._last_attempt < RETRY_SECONDS:
            return None
        self._last_attempt = now
        if node_id is None:
            self.state, self.error = "failed", "no node id (enrolled before heartbeats; re-enroll)"
            return None
        try:
            new_key = prove_new_server(new_url, token, int(node_id), stmt["new_key_fp"])
            info = device_info(new_url, token)
            if info.get("node_id") != node_id or (
                e.get("network_id") is not None and info.get("network_id") != e.get("network_id")
            ):
                raise MoveError("new server has this device as a different node or network")
        except MoveError as err:
            self.state, self.error = "failed", str(err)
            self._log(f"server move to {new_url} not done yet: {err}")
            return None
        self.state, self.error = "switching", None
        try:
            send_switching()
        except Exception:  # the old server only shows progress with it
            pass
        self._update(server=new_url, previous_server=base, instance_key=new_key,
                     pinned_domain=registrable_domain(host_of(new_url)), pending_move=None, moved_at=now)
        self._log(f"server move: now using {new_url} (was {base})")
        return new_url
