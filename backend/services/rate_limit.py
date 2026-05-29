"""Simple in-memory request rate limiting middleware."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import threading
import time
from typing import Deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


@dataclass(frozen=True)
class LimitRule:
    """A request limit rule for a bucket/window pair."""

    requests: int
    window_seconds: int


class InMemoryRateLimiter:
    """Thread-safe in-memory sliding-window limiter."""

    def __init__(self) -> None:
        self._events: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, rule: LimitRule) -> tuple[bool, int, int]:
        now = time.monotonic()
        cutoff = now - rule.window_seconds

        with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= rule.requests:
                reset_in = max(1, int(rule.window_seconds - (now - bucket[0])))
                return False, 0, reset_in

            bucket.append(now)
            remaining = max(0, rule.requests - len(bucket))
            reset_in = max(1, int(rule.window_seconds - (now - bucket[0])))
            return True, remaining, reset_in


def parse_csv_paths(raw: str) -> list[str]:
    """Parse comma-separated paths into normalized prefixes."""
    values = [part.strip() for part in raw.split(",") if part.strip()]
    normalized: list[str] = []
    for value in values:
        normalized.append(value if value.startswith("/") else f"/{value}")
    return normalized


def get_client_ip(request: Request, trust_proxy_headers: bool) -> str:
    """Resolve client IP from request safely."""
    if trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            first_ip = forwarded_for.split(",", 1)[0].strip()
            if first_ip and first_ip.lower() != "unknown":
                return first_ip

    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply global and auth-specific request rate limits."""

    def __init__(
        self,
        app,
        *,
        default_rule: LimitRule,
        auth_rule: LimitRule,
        exempt_paths: list[str],
        auth_paths: list[str],
        trust_proxy_headers: bool,
    ) -> None:
        super().__init__(app)
        self._default_rule = default_rule
        self._auth_rule = auth_rule
        self._exempt_paths = exempt_paths
        self._auth_paths = auth_paths
        self._trust_proxy_headers = trust_proxy_headers
        self._limiter = InMemoryRateLimiter()

    def _is_exempt(self, request: Request) -> bool:
        path = request.url.path
        if request.method == "OPTIONS":
            return True
        return any(path.startswith(prefix) for prefix in self._exempt_paths)

    def _rule_for_path(self, path: str) -> LimitRule:
        if any(path.startswith(prefix) for prefix in self._auth_paths):
            return self._auth_rule
        return self._default_rule

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._is_exempt(request):
            return await call_next(request)

        path = request.url.path
        rule = self._rule_for_path(path)
        client_ip = get_client_ip(request, self._trust_proxy_headers)
        key = f"{client_ip}:{path}"

        allowed, remaining, reset_in = self._limiter.check(key, rule)
        if not allowed:
            headers = {
                "Retry-After": str(reset_in),
                "X-RateLimit-Limit": str(rule.requests),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_in),
            }
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please retry later."},
                headers=headers,
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(rule.requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_in)
        return response
