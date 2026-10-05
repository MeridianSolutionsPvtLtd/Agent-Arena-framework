"""Safe error responses must never expose exception or submitted secret values."""

import asyncio

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from middleware.error_handlers import (
    safe_http_exception_handler,
    safe_unhandled_exception_handler,
    safe_validation_exception_handler,
)


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/test", "headers": []})


def test_server_http_exception_hides_internal_detail():
    response = asyncio.run(
        safe_http_exception_handler(
            _request(), HTTPException(status_code=500, detail="password=super-secret")
        )
    )

    assert response.status_code == 500
    assert response.body == b'{"detail":"Internal server error"}'
    assert b"super-secret" not in response.body


def test_expected_client_error_keeps_actionable_detail():
    response = asyncio.run(
        safe_http_exception_handler(
            _request(), HTTPException(status_code=404, detail="Agent not found")
        )
    )

    assert response.status_code == 404
    assert response.body == b'{"detail":"Agent not found"}'


def test_validation_error_does_not_echo_submitted_value():
    exc = RequestValidationError(
        [
            {
                "type": "string_too_short",
                "loc": ("body", "password"),
                "msg": "String should have at least 12 characters",
                "input": "secret-value",
                "ctx": {"min_length": 12},
            }
        ]
    )
    response = asyncio.run(safe_validation_exception_handler(_request(), exc))

    assert response.status_code == 422
    assert b"secret-value" not in response.body
    assert b"password" in response.body


def test_unhandled_exception_returns_generic_response():
    response = asyncio.run(
        safe_unhandled_exception_handler(_request(), RuntimeError("token=private-token"))
    )

    assert response.status_code == 500
    assert response.body == b'{"detail":"Internal server error"}'
    assert b"private-token" not in response.body
