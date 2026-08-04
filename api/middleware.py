import asyncio
import logging
import secrets
import time
from collections import defaultdict, deque
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("finecho.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", uuid4().hex)
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(duration_ms)
        logger.info(
            "request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        try:
            too_large = bool(content_length) and int(content_length) > self.max_bytes
        except ValueError:
            too_large = True
        if too_large:
            return JSONResponse(
                status_code=413,
                content={"code": "payload_too_large", "message": "请求体超过大小限制"},
            )
        return await call_next(request)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str, excluded_paths: set[str] | None = None) -> None:
        super().__init__(app)
        self.api_key = api_key
        self.excluded_paths = excluded_paths or set()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.api_key or request.url.path in self.excluded_paths:
            return await call_next(request)
        supplied = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(supplied, self.api_key):
            return JSONResponse(
                status_code=401,
                content={"code": "unauthorized", "message": "无效或缺少 X-API-Key"},
            )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests: int, window_seconds: int) -> None:
        super().__init__(app)
        self.limit = requests
        self.window = window_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        client = forwarded or (request.client.host if request.client else "unknown")
        now = time.monotonic()
        async with self.lock:
            bucket = self.hits[client]
            while bucket and now - bucket[0] >= self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, int(self.window - (now - bucket[0])))
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    content={"code": "rate_limited", "message": "请求过于频繁，请稍后重试"},
                )
            bucket.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.limit - len(bucket)))
        return response
