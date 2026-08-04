from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from api.errors import finecho_error_handler, unhandled_error_handler, validation_error_handler
from api.middleware import (
    ApiKeyMiddleware,
    BodyLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from api.router import api_router
from api.routes.health import router as health_router
from app.config import get_settings
from app.lifespan import lifespan
from src.core.exceptions import FinEchoError
from src.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="突发政策产业链归因与上市公司受益真实性核验 API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
app.add_middleware(
    ApiKeyMiddleware,
    api_key=settings.api_key,
    excluded_paths={"/health", "/ready", "/docs", "/openapi.json"},
)
app.add_middleware(
    RateLimitMiddleware,
    requests=settings.rate_limit_requests,
    window_seconds=settings.rate_limit_window_seconds,
)
app.add_middleware(RequestContextMiddleware)

app.add_exception_handler(FinEchoError, finecho_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_prefix)
