"""Rate limiting middleware for sensitive endpoints."""
import time
from collections import defaultdict
from typing import Dict, Tuple
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiting middleware.
    
    For production, consider using Redis-backed rate limiting.
    """
    
    def __init__(self, app):
        super().__init__(app)
        # Store: {(client_id, endpoint_id): [timestamp, ...]}
        self.requests: Dict[Tuple[str, str], list] = defaultdict(list)
        
        # Rate limits: {endpoint_pattern: (max_requests, window_seconds)}
        self.limits = {
            # Device enrollment: protect against brute-forcing short codes
            "/api/device/enroll": (5, 900),  # 5 requests per 15 minutes per IP
            # Device config/certs: per-device token to avoid throttling many devices behind one IP
            "/api/device/config": (600, 3600),  # ~10 requests per minute per device
            "/api/device/certs": (20, 3600),  # infrequent cert downloads per device
            # Auth / login flows
            "/api/auth/dev-token": (10, 60),  # 10 requests per minute
            "/api/auth/login": (10, 60),  # 10 requests per minute
            "/api/auth/callback": (20, 60),  # 20 requests per minute
            "/api/auth/reauth/challenge": (20, 900),  # 20 reauth challenges per 15 minutes per IP
            "/api/auth/reauth/callback": (40, 900),  # callbacks can be a bit higher
            # Public invitation preview: protect against brute-forcing invitation tokens
            "/api/invitations/public": (30, 3600),  # 30 requests per hour per IP
        }
    
    async def dispatch(self, request: Request, call_next):
        """Check rate limit before processing request."""
        path = request.url.path
        
        # Check if this path needs rate limiting
        limit_config = None
        endpoint_id = None
        for pattern, config in self.limits.items():
            # Exact match (e.g. /api/auth/login) or prefix match for variable segments
            # (e.g. /api/invitations/public/{token}).
            if path == pattern or path.startswith(pattern + "/"):
                limit_config = config
                endpoint_id = pattern
                break
        
        if limit_config and endpoint_id:
            max_requests, window_seconds = limit_config

            # Choose an identifier for the client:
            # - For device-token–protected endpoints, prefer the Authorization header so
            #   multiple devices behind one IP are tracked separately.
            # - For everything else, fall back to client IP.
            if endpoint_id in ("/api/device/config", "/api/device/certs"):
                auth_header = (request.headers.get("authorization") or "").strip()
                if auth_header:
                    client_id = auth_header
                else:
                    client_id = request.client.host if request.client else "unknown"
            else:
                client_id = request.client.host if request.client else "unknown"

            key = (client_id, endpoint_id)
            
            # Clean old entries
            now = time.time()
            self.requests[key] = [
                ts for ts in self.requests[key]
                if now - ts < window_seconds
            ]
            
            # Check if limit exceeded
            if len(self.requests[key]) >= max_requests:
                logger.warning(
                    "Rate limit exceeded for %s on %s (%d requests in %d seconds)",
                    client_id, endpoint_id, len(self.requests[key]), window_seconds
                )
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds} seconds."
                )
            
            # Record this request
            self.requests[key].append(now)
        
        response = await call_next(request)
        return response
