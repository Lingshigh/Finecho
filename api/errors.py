import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.core.exceptions import FinEchoError

logger = logging.getLogger(__name__)


async def finecho_error_handler(request: Request, exc: FinEchoError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "request_id": getattr(request.state, "request_id", None),
            "details": exc.details,
        },
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": "请求参数校验失败",
            "request_id": getattr(request.state, "request_id", None),
            "details": {"errors": exc.errors()},
        },
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API error")
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "服务器内部错误",
            "request_id": getattr(request.state, "request_id", None),
        },
    )
