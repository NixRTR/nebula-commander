"""Server move middleware (backend/api/move.py).

While a move is active:
- every /api/device/* response carries the signed move statement header, 304s and
  errors included, so ncclient sees it on whatever its poll gets back;
- the instance is read-only: writes that would make it drift from the instance the
  devices are moving to are refused with 423. Logging in, devices, personal
  preferences, export and cancelling the move still work.
"""
import logging
import time
from typing import Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..services import instance_identity

logger = logging.getLogger(__name__)

_WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
_WRITE_ALLOWED_PREFIXES = (
    "/api/auth/",
    "/api/device/",
    "/api/users/me/",
    "/api/admin/move/cancel",
    "/api/admin/export",
)
_CACHE_SECONDS = 5.0

# (checked_at, header value or None, new_url or None); shared by every middleware
# instance in this process so the move API can invalidate it.
_state: dict = {"at": 0.0, "header": None, "new_url": None}


def invalidate() -> None:
    _state["at"] = 0.0


class MoveMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, session_factory: Callable):
        super().__init__(app)
        self.session_factory = session_factory

    async def _current(self) -> tuple[Optional[str], Optional[str]]:
        now = time.monotonic()
        if now - _state["at"] > _CACHE_SECONDS:
            try:
                async with self.session_factory() as session:
                    move = await instance_identity.active_move(session)
                _state["header"] = instance_identity.wire(move.body, move.signature) if move else None
                _state["new_url"] = move.new_url if move else None
            except Exception as e:  # tables not created yet (startup) - no move
                logger.debug("move state lookup failed: %s", e)
                _state["header"], _state["new_url"] = None, None
            _state["at"] = now
        return _state["header"], _state["new_url"]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        header, new_url = await self._current()
        if header is None:
            return await call_next(request)
        if (
            request.method in _WRITE_METHODS
            and not path.startswith(_WRITE_ALLOWED_PREFIXES)
            and not path.endswith("/heartbeat")
        ):
            return JSONResponse(
                status_code=423,
                content={"detail": f"This instance is moving to {new_url} and is read-only. "
                                   "Cancel the move to make changes here."},
            )
        response = await call_next(request)
        if path.startswith("/api/device/"):
            response.headers[instance_identity.MOVE_HEADER] = header
        return response
