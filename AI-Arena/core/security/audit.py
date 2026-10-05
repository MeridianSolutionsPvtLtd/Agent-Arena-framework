import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict
import hashlib


audit_logger = logging.getLogger("safety_audit")
IST = timezone(timedelta(hours=5, minutes=30))


def _utc_ts() -> str:
    return datetime.now(IST).isoformat()


def emit_audit_event(event_type: str, **fields: Any) -> None:
    """
    Emit a single structured audit event as JSON.
    This keeps logs machine-parseable for incident review and dashboards.
    """
    payload: Dict[str, Any] = {
        "ts": _utc_ts(),
        "event_type": event_type,
        "service": "agent_arena_backend",
    }
    payload.update(fields)
    try:
        audit_logger.info(json.dumps(payload, ensure_ascii=True, default=str))
    except Exception:
        # Never let audit logging break request flow.
        audit_logger.exception("failed_to_emit_audit_event")


def hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def preview_text(text: str, limit: int = 600) -> str:
    raw = (text or "").replace("\r\n", "\n")
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "...[truncated]"
