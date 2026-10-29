"""
Moved-only mode (NEBULA_COMMANDER_MOVED_ONLY_FILE=/path/move-responder.json): what the
old instance runs after its devices moved, so ones that were offline still find the
new server. No database, no OIDC - only the signed statement from the Move page.

/api/device/* answers 410 with the statement in the move header (never 401: ncclient
treats that as revoked), GET /api/device/move returns it, and / says where it went.

Once the recommended period (the Move page's "keep answering for") is over, the admins
named in the file get one email with the small standalone responder
(backend/move_responder.py) and reverse-proxy snippets, so the old domain's root can be
used for something else while /api/device/ keeps pointing devices at the new server.
"""
import asyncio
import html
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .move_responder import MOVE_HEADER, load

logger = logging.getLogger(__name__)

CHECK_SECONDS = 3600

PROXY_SNIPPETS = """\
Run it (Python 3, no other dependencies):

    python3 move_responder.py move-responder.json --port 8099

and send only /api/device/ on {host} to it, e.g.

  nginx:
    location /api/device/ {{ proxy_pass http://127.0.0.1:8099; }}

  Caddy:
    handle /api/device/* {{ reverse_proxy 127.0.0.1:8099 }}

  Traefik (docker labels):
    traefik.http.routers.nc-move.rule=Host(`{host}`) && PathPrefix(`/api/device/`)
"""


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.rstrip("Z"))


def _marker(path: str) -> Path:
    return Path(path + ".notified")


async def notify_if_due(path: str, data: dict, now: datetime | None = None) -> bool:
    """Send the end-of-period email once. True when it was sent now."""
    from .services.email import send_plain_email

    now = now or datetime.utcnow()
    if now < _parse_time(data["recommended_until"]) or _marker(path).exists():
        return False
    host = urlparse(data.get("old_url") or "").hostname or "the old server"
    text = (
        f"The recommended period for keeping {data.get('old_url')} answering for moved devices "
        f"ended on {data['recommended_until']}.\n\n"
        f"Devices that were online since the move are on {data['new_url']} now. Any that were off "
        "the whole time still look for the old address. Devices accept the move until "
        f"{data['expires_at']}.\n\n"
        "To use the old domain for something else and still catch those devices, replace this "
        "Nebula Commander instance with the small responder attached (move_responder.py) and "
        "route only /api/device/ to it.\n\n" + PROXY_SNIPPETS.format(host=host) +
        "\n---\nNebula Commander\n"
    )
    responder = Path(__file__).with_name("move_responder.py").read_bytes()
    with open(path, "rb") as f:
        responder_json = f.read()
    sent = await send_plain_email(
        list(data.get("admin_emails") or []),
        f"Nebula Commander: {host} can be retired",
        text,
        [("move_responder.py", responder, "text/x-python"), ("move-responder.json", responder_json, "application/json")],
    )
    if sent:
        _marker(path).write_text(now.isoformat() + "Z\n", encoding="utf-8")
    else:
        logger.warning("Moved-only mode: the end-of-period email to %s could not be sent "
                       "(SMTP off or failing); will retry", data.get("admin_emails"))
    return sent


def create_app(path: str) -> FastAPI:
    data = load(path)
    statement = str(data["statement"])
    new_url = str(data["new_url"])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Moved-only mode: pointing devices at %s", new_url)

        async def loop():
            while True:
                try:
                    await notify_if_due(path, data)
                except Exception as e:  # never take the responder down
                    logger.warning("Moved-only mode: notification check failed: %s", e)
                await asyncio.sleep(CHECK_SECONDS)

        task = asyncio.create_task(loop())
        yield
        task.cancel()

    app = FastAPI(title="Nebula Commander (moved)", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.api_route("/api/device/move", methods=["GET", "HEAD"])
    async def device_move():
        return PlainTextResponse(statement, headers={MOVE_HEADER: statement, "Cache-Control": "no-store"})

    @app.api_route("/api/device/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
    async def device_any(rest: str):
        return JSONResponse(
            status_code=410,
            content={"detail": f"This server has moved to {new_url}"},
            headers={MOVE_HEADER: statement, "Cache-Control": "no-store"},
        )

    @app.get("/api/health")
    async def health():
        return {"status": "moved", "new_url": new_url}

    @app.get("/{rest:path}", include_in_schema=False)
    async def moved_page(rest: str):
        url = html.escape(new_url, quote=True)
        return HTMLResponse(
            status_code=410,
            content=(
                "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>Moved</title><body style='font-family:system-ui,sans-serif;max-width:40em;margin:4em auto;padding:0 1em'>"
                f"<h1>This Nebula Commander server has moved</h1><p>It is now at <a href=\"{url}\">{url}</a>.</p>"
                "<p>Devices move over by themselves.</p></body>"
            ),
        )

    return app


def moved_only_path() -> str | None:
    from .config import settings

    path = (settings.moved_only_file or "").strip()
    if path and not os.path.isfile(path):
        raise SystemExit(f"NEBULA_COMMANDER_MOVED_ONLY_FILE={path} does not exist")
    return path or None

