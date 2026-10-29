"""
Moved-only mode (backend/moved_only.py) and the standalone responder
(backend/move_responder.py): device paths get 410 + the statement (never 401), and the
admins get one email once the recommended period is over.
"""
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer

import pytest
from httpx import ASGITransport, AsyncClient

from backend import move_responder, moved_only

STATEMENT = "eyJ2IjoxfQ.c2ln"


@pytest.fixture
def responder_file(tmp_path):
    path = tmp_path / "move-responder.json"
    path.write_text(json.dumps({
        "v": 1, "statement": STATEMENT, "old_url": "https://nebulacdr.net",
        "new_url": "https://beardedtek.nebulacdr.net", "switch_at": "2026-10-29T00:00:00Z",
        "recommended_until": "2026-11-28T00:00:00Z", "expires_at": "2027-10-28T00:00:00Z",
        "admin_emails": ["admin@example.com"],
    }), encoding="utf-8")
    return str(path)


@pytest.mark.asyncio
async def test_device_paths_get_410_and_the_statement(responder_file):
    app = moved_only.create_app(responder_file)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        for method, path in (("GET", "/api/device/config"), ("POST", "/api/nodes/../device/x"),
                             ("POST", "/api/device/move-proof"), ("GET", "/api/device/info")):
            r = await api.request(method, path, headers={"Authorization": "Bearer stale"})
            if path.startswith("/api/device/"):
                assert r.status_code == 410, path
                assert r.headers[move_responder.MOVE_HEADER] == STATEMENT
        r = await api.get("/api/device/move")
        assert r.status_code == 200 and r.text == STATEMENT
        r = await api.get("/")
        assert r.status_code == 410 and "beardedtek.nebulacdr.net" in r.text


@pytest.mark.asyncio
async def test_email_once_after_the_recommended_period(responder_file, monkeypatch):
    sent = []

    async def fake_send(to, subject, text, attachments):
        sent.append((to, subject, text, [a[0] for a in attachments]))
        return True

    monkeypatch.setattr("backend.services.email.send_plain_email", fake_send)
    data = move_responder.load(responder_file)
    assert await moved_only.notify_if_due(responder_file, data, now=datetime(2026, 11, 1)) is False
    assert await moved_only.notify_if_due(responder_file, data, now=datetime(2026, 12, 1)) is True
    assert await moved_only.notify_if_due(responder_file, data, now=datetime(2026, 12, 2)) is False
    assert len(sent) == 1
    to, subject, text, files = sent[0]
    assert to == ["admin@example.com"] and "nebulacdr.net" in subject
    assert "location /api/device/" in text
    assert files == ["move_responder.py", "move-responder.json"]


@pytest.mark.asyncio
async def test_failed_email_is_retried(responder_file, monkeypatch):
    async def fail(*a, **k):
        return False

    monkeypatch.setattr("backend.services.email.send_plain_email", fail)
    data = move_responder.load(responder_file)
    assert await moved_only.notify_if_due(responder_file, data, now=datetime(2026, 12, 1)) is False
    assert not moved_only._marker(responder_file).exists()


def test_standalone_responder(responder_file):
    server = ThreadingHTTPServer(("127.0.0.1", 0), move_responder.make_handler(move_responder.load(responder_file)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{base}/api/device/config")
        assert e.value.code == 410 and e.value.headers[move_responder.MOVE_HEADER] == STATEMENT
        with urllib.request.urlopen(f"{base}/api/device/move") as r:
            assert r.read().decode() == STATEMENT
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{base}/")
        assert e.value.code == 404 and move_responder.MOVE_HEADER not in e.value.headers
    finally:
        server.shutdown()
