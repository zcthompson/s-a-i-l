"""Rate limiting middleware to prevent abuse of scoring endpoints."""

import os
import time
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Rate limiting configuration
# Default raised 1000 → 10000/hour — the old budget was exhausted
# mid-suite by the full test run (and is tight for production use as the
# app integrates more API surfaces). Env-overridable as before.
# Read through Settings at import time (.env is
# loaded before this import; the per-process env is stable).
from backend.auth import resolve_auth_enabled
from backend.config import get_settings

_settings = get_settings()
RATE_LIMIT_REQUESTS = _settings.rate_limit_requests  # requests per window
RATE_LIMIT_WINDOW = _settings.rate_limit_window  # window in seconds (1 hour)
LOGIN_RATE_LIMIT_REQUESTS = _settings.login_rate_limit_requests
LOGIN_RATE_LIMIT_WINDOW = _settings.login_rate_limit_window
REGISTER_RATE_LIMIT_REQUESTS = _settings.register_rate_limit_requests
REGISTER_RATE_LIMIT_WINDOW = _settings.register_rate_limit_window

# Per-endpoint rate limits
ENDPOINT_RATE_LIMITS: dict[str, tuple[int, int]] = {
    "/api/auth/login": (LOGIN_RATE_LIMIT_REQUESTS, LOGIN_RATE_LIMIT_WINDOW),
    "/api/auth/register": (REGISTER_RATE_LIMIT_REQUESTS, REGISTER_RATE_LIMIT_WINDOW),
    "/api/scoring/": (RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW),
    "/api/bulk/": (RATE_LIMIT_REQUESTS // 2, RATE_LIMIT_WINDOW),  # Stricter for bulk operations
    "/api/stats/export-csv": (RATE_LIMIT_REQUESTS // 5, RATE_LIMIT_WINDOW),  # Stricter for export
}


class RateLimiter:
    """Simple in-memory rate limiter with bounded storage."""

    def __init__(self, max_entries: int = 10000):
        self.requests: dict[tuple[str, str], list] = defaultdict(list)
        self.max_entries = max_entries
        self._cleanup_count = 0

    @staticmethod
    def get_limit(endpoint: str) -> tuple[str, int, int]:
        """Return the canonical bucket name and its configured limit."""
        if endpoint in ENDPOINT_RATE_LIMITS:
            bucket = endpoint
        elif endpoint != "/" and endpoint.endswith("/") and endpoint[:-1] in ENDPOINT_RATE_LIMITS:
            bucket = endpoint[:-1]
        else:
            bucket = endpoint
        max_requests, window = ENDPOINT_RATE_LIMITS.get(
            bucket, (RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW)
        )
        return bucket, max_requests, window

    def is_allowed(self, client_ip: str, endpoint: str) -> bool:
        """Check if a request is allowed."""
        now = time.time()

        # Get rate limit for endpoint
        bucket, max_requests, window = self.get_limit(endpoint)
        key = (client_ip, bucket)

        # Clean old requests
        self.requests[key] = [
            req_time for req_time in self.requests[key]
            if req_time > now - window
        ]

        # Clean up oldest entries if we're hitting the limit (bounded storage)
        if len(self.requests) > self.max_entries:
            # Sort by oldest entry and remove oldest 20%
            sorted_ips = sorted(self.requests.items(), 
                              key=lambda x: min(x[1]) if x[1] else 0)
            remove_count = len(sorted_ips) // 5
            for request_key, _ in sorted_ips[:remove_count]:
                del self.requests[request_key]

        # Check if limit exceeded
        if len(self.requests[key]) >= max_requests:
            return False

        # Record request
        self.requests[key].append(now)
        return True

    def get_remaining(self, client_ip: str, endpoint: str) -> int:
        """Get remaining requests."""
        now = time.time()

        bucket, max_requests, window = self.get_limit(endpoint)
        key = (client_ip, bucket)

        # Clean old requests
        self.requests[key] = [
            req_time for req_time in self.requests[key]
            if req_time > now - window
        ]

        return max(0, max_requests - len(self.requests[key]))


# Global rate limiter instance
rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware."""

    async def dispatch(self, request: Request, call_next):
        """Process request and apply rate limiting."""
        path = request.url.path

        # Skip rate limiting for public routes and static assets
        public_prefixes = (
            "/health", "/readyz", "/openapi.json", "/docs", "/redoc", "/favicon.ico",
            "/assets/", "/login", "/static/",
        )
        if any(path.startswith(p) for p in public_prefixes):
            return await call_next(request)

        # Skip rate limiting if auth is disabled — per-request read BY
        # DESIGN (the SEC-02 bucket test monkeypatches SAIL_API_KEYS
        # per-request, and a deployment can flip the switch without a
        # restart; the same by-design pattern as SAIL_TRUSTED_PROXIES).
        # An import-time snapshot of Settings broke this on hosts without
        # .env (CI — run 41343429538, first unblocked run 2026-11-01).
        if not resolve_auth_enabled(os.environ.get("SAIL_AUTH_ENABLED", ""),
                                    os.environ.get("SAIL_API_KEYS", "")):
            return await call_next(request)

        client_ip = self.get_client_ip(request)

        # Only rate limit API endpoints (not SPA fallback routes)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Check rate limit
        _, max_requests, window = rate_limiter.get_limit(path)
        if not rate_limiter.is_allowed(client_ip, path):
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Try again later.",
                    "retry_after": window
                },
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + window),
                }
            )

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        remaining = rate_limiter.get_remaining(client_ip, request.url.path)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + window)

        return response

    def get_client_ip(self, request: Request) -> str:
        """Get client IP address."""
        direct_peer = request.client.host if request.client else "unknown"
        # Per-request env read by design: the
        # trusted-proxy set is runtime-overridable and pinned as such by
        # test_security_sec0234 — unlike the import-time budgets above.
        trusted_proxies = {
            proxy.strip()
            for proxy in os.environ.get("SAIL_TRUSTED_PROXIES", "").split(",")
            if proxy.strip()
        }
        if direct_peer not in trusted_proxies:
            return direct_peer

        forwarded_for = request.headers.get("X-Forwarded-For", "")
        for forwarded_ip in forwarded_for.split(","):
            if forwarded_ip.strip():
                return forwarded_ip.strip()

        real_ip = request.headers.get("X-Real-IP", "").strip()
        return real_ip or direct_peer
