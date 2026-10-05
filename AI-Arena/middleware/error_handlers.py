"""Application-wide safe HTTP error responses.

Expected client errors may retain their deliberately authored messages. Server and
upstream failures are always replaced with stable public text; the underlying
exception remains available only in server logs.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from utils.logger import get_logger


logger = get_logger(__name__)


_SAFE_SERVER_DETAILS = {
    500: "Internal server error",
    501: "Operation is not implemented",
    502: "Upstream service is unavailable",
    503: "Service is temporarily unavailable",
    504: "Upstream service timed out",
}

_SAFE_ERROR_CODES = {
    "local_model_timeout",
    "local_model_unavailable",
    "mcp_timeout",
    "mcp_unavailable",
    "external_mcp_timeout",
    "external_mcp_unavailable",
    "external_mcp_authentication_required",
    "external_mcp_entitlement_required",
    "external_mcp_rate_limited",
    "invalid_mcp_result",
    "tool_execution_failed",
    "summarization_failed",
}


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Return actionable validation errors without echoing request values."""

    safe_errors: list[dict[str, Any]] = []
    for error in exc.errors():
        safe_error = {
            "type": error.get("type", "value_error"),
            "loc": list(error.get("loc") or []),
            "msg": error.get("msg", "Invalid value"),
        }
        safe_errors.append(safe_error)
    return safe_errors


async def safe_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error(
            "HTTP request failed with a server-side error",
            extra={"status_code": exc.status_code},
        )
        # Preserve only normalized, allow-listed provider error details. Never
        # expose exception objects, stack traces, credentials, or raw payloads.
        raw_detail = exc.detail
        if isinstance(raw_detail, dict) and raw_detail.get("code") in _SAFE_ERROR_CODES:
            detail = {
                "code": raw_detail["code"],
                "message": str(raw_detail.get("message") or _SAFE_SERVER_DETAILS.get(exc.status_code, "Server request failed")),
                "retryable": bool(raw_detail.get("retryable", False)),
            }
        else:
            detail = _SAFE_SERVER_DETAILS.get(exc.status_code, "Server request failed")
    else:
        detail = exc.detail
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
        headers=exc.headers,
    )


async def safe_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": _safe_validation_errors(exc)})


async def safe_unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled request exception",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"status_code": 500},
    )
    return JSONResponse(status_code=500, content={"detail": _SAFE_SERVER_DETAILS[500]})


def register_safe_error_handlers(app: FastAPI) -> None:
    """Install the final public error boundary for every application router."""

    app.add_exception_handler(StarletteHTTPException, safe_http_exception_handler)
    app.add_exception_handler(HTTPException, safe_http_exception_handler)
    app.add_exception_handler(RequestValidationError, safe_validation_exception_handler)
    app.add_exception_handler(Exception, safe_unhandled_exception_handler)
