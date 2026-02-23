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
        # Store: {(ip, endpoint): [(timestamp, count), ...]}
        self.requests: Dict[Tuple[str, str], list] = defaultdict(list)
        
        # Rate limits: {endpoint_pattern: (max_requests, window_seconds)}
        self.limits = {
            "/api/device/enroll": (100, 900),  # 100 requests per 15 minutes
            "/api/auth/dev-token": (10, 60),  # 10 requests per minute
            "/api/auth/login": (10, 60),  # 10 requests per minute
            "/api/auth/callback": (20, 60),  # 20 requests per minute
        }
    
    async def dispatch(self, request: Request, call_next):
        """Check rate limit before processing request."""
        path = request.url.path
        
        # Check if this path needs rate limiting
        limit_config = None
        for pattern, config in self.limits.items():
            if path == pattern:
                limit_config = config
                break
        
        if limit_config:
            max_requests, window_seconds = limit_config
            client_ip = request.client.host if request.client else "unknown"
            key = (client_ip, path)
            
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
                    client_ip, path, len(self.requests[key]), window_seconds
                )
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds} seconds."
                )
            
            # Record this request
            self.requests[key].append(now)
        
        response = await call_next(request)
        return response
