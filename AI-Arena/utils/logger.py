import logging
import json
import datetime
import contextvars
import os
from typing import Optional, Any

# Context variables to hold request-specific information
request_id_ctx = contextvars.ContextVar("request_id", default="system")
user_id_ctx = contextvars.ContextVar("user_id", default="system")
service_name_ctx = contextvars.ContextVar("service_name", default="meridian-backend")

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "service": service_name_ctx.get(),
            "layer": "backend",
            "module": record.module,
            "function": record.funcName,
            "log_level": record.levelname,
            "message": record.getMessage(),
            "status_code": getattr(record, "status_code", 0),
            "request_id": request_id_ctx.get(),
            "user_id": user_id_ctx.get(),
        }
        
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_record)


class TerminalJSONFormatter(JSONFormatter):
    """Keep structured JSON while making terminal stages easy to scan.

    INFO (successful/progress) is green, WARNING (approval/waiting/fallback)
    is yellow, and ERROR/CRITICAL (failed stages) is red. ``NO_COLOR=1``
    disables ANSI escapes for CI and log collectors.
    """

    _COLORS = {
        logging.INFO: "\x1b[32m",       # green
        logging.WARNING: "\x1b[33m",   # yellow
        logging.ERROR: "\x1b[31m",     # red
        logging.CRITICAL: "\x1b[1;31m",
    }
    _RESET = "\x1b[0m"

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if os.getenv("NO_COLOR", "").lower() in {"1", "true", "yes"}:
            return message
        color = self._COLORS.get(record.levelno)
        return f"{color}{message}{self._RESET}" if color else message

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Avoid adding multiple handlers if get_logger is called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = TerminalJSONFormatter()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger


def pipeline_event(stage: str, event: str, **fields: Any) -> None:
    """Emit a compact, colorized lifecycle event for terminal debugging."""
    payload = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    get_logger("pipeline").info("[%s] %s%s", stage, event, f" {payload}" if payload else "")
