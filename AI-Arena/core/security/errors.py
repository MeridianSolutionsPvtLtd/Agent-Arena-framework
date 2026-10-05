import logging
from typing import Optional

from fastapi import HTTPException, Request


logger = logging.getLogger(__name__)


def request_id_from_request(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    return getattr(getattr(request, "state", None), "request_id", None)


def safe_http_error(
    *,
    logger_name: str,
    exc: Exception,
    user_message: str,
    status_code: int = 500,
    request: Optional[Request] = None,
    request_id: Optional[str] = None,
    **context,
) -> HTTPException:
    """Log full internal error and return a frontend-safe HTTPException."""
    rid = request_id or request_id_from_request(request)
    log = logging.getLogger(logger_name)
    log.exception(
        "%s request_id=%s context=%s",
        user_message,
        rid or "unavailable",
        {k: v for k, v in context.items() if v is not None},
        exc_info=exc,
    )
    detail = {"message": user_message}
    if rid:
        detail["request_id"] = rid
    return HTTPException(status_code=status_code, detail=detail)

