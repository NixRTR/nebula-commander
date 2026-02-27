import time
from typing import Dict, Tuple

from fastapi import FastAPI
from fastapi.testclient import TestClient

from .middleware.rate_limit import RateLimitMiddleware


def create_app_with_rate_limit(overrides: Dict[str, Tuple[int, int]] | None = None) -> TestClient:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    # Attach a simple ping route so we can exercise the middleware
    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    # Optionally override limits for this test instance
    if overrides is not None:
        middleware = None
        for m in app.user_middleware:
            if m.cls is RateLimitMiddleware:
                # Mounted middleware instance is created lazily; force instantiation via app.router.
                # After that, we can access it from app.middleware_stack.
                break
        # Access the instantiated middleware stack to get our RateLimitMiddleware instance
        current = app.middleware_stack
        while current:
            if isinstance(getattr(current, "app", None), RateLimitMiddleware):
                middleware = current.app
                break
            current = getattr(current, "app", None)
        if middleware is not None:
            middleware.limits.update(overrides)

    return TestClient(app)


def test_rate_limit_per_ip_basic():
    client = create_app_with_rate_limit({"/ping": (2, 60)})

    # First two requests should pass
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200

    # Third request within the window should be rate-limited
    resp = client.get("/ping")
    assert resp.status_code == 429


def test_rate_limit_per_device_token_separate_from_ip():
    # Configure a generous limit for /api/device/config but keyed by Authorization
    client = create_app_with_rate_limit({"/api/device/config": (2, 60)})

    headers_a = {"authorization": "Bearer token-a"}
    headers_b = {"authorization": "Bearer token-b"}

    # Mount a simple route that uses the device config path
    @client.app.get("/api/device/config")
    async def device_config():
        return {"status": "ok"}

    # Two requests from token-a should pass
    assert client.get("/api/device/config", headers=headers_a).status_code == 200
    assert client.get("/api/device/config", headers=headers_a).status_code == 200

    # Third request from token-a should be limited
    resp_a = client.get("/api/device/config", headers=headers_a)
    assert resp_a.status_code == 429

    # token-b should still be allowed independently
    assert client.get("/api/device/config", headers=headers_b).status_code == 200


def test_invitations_public_prefix_matching():
    client = create_app_with_rate_limit({"/api/invitations/public": (1, 60)})

    @client.app.get("/api/invitations/public/{token}")
    async def invitation_public(token: str):
        return {"token": token}

    # First token lookup should pass
    assert client.get("/api/invitations/public/abc").status_code == 200

    # Second lookup (different token) from the same IP should be limited due to shared prefix
    resp = client.get("/api/invitations/public/def")
    assert resp.status_code == 429

