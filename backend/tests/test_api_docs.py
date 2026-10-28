"""API docs are served under /api (so the proxy reaches them) and can be turned off."""
import importlib

import pytest
from fastapi.testclient import TestClient


def _load_app(monkeypatch, enabled):
    from backend import config, main

    monkeypatch.setattr(config.settings, "api_docs_enabled", enabled)
    return importlib.reload(main).app


@pytest.fixture(autouse=True)
def _restore_main():
    yield
    from backend import main

    importlib.reload(main)


def test_docs_enabled_serves_schema_under_api(monkeypatch):
    client = TestClient(_load_app(monkeypatch, True))
    schema = client.get("/api/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["openapi"].startswith("3.")
    docs = client.get("/api/docs")
    assert docs.status_code == 200
    assert "/api/openapi.json" in docs.text
    assert "/api/openapi.json" in client.get("/api/redoc").text
    assert client.get("/openapi.json").status_code == 404


def test_docs_disabled(monkeypatch):
    client = TestClient(_load_app(monkeypatch, False))
    for path in ("/api/openapi.json", "/api/docs", "/api/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path
