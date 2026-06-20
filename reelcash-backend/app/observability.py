"""Structured JSON logging, trace-id propagation, and an alert hook.

Every log line carries a ``trace_id`` (the video id) so a single video's
whole journey through the async pipeline can be filtered in one query.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from typing import Any, Optional

import httpx

from .config import settings

# The trace id flows automatically through async tasks via contextvars.
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


def set_trace_id(trace_id: str) -> None:
    _trace_id.set(trace_id or "-")


def get_trace_id() -> str:
    return _trace_id.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": getattr(record, "trace_id", None) or get_trace_id(),
        }
        # Merge any structured extras attached via logger.*(..., extra={...}).
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = get_trace_id()
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL.upper())
    handler = logging.StreamHandler(sys.stdout)
    if settings.LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(trace_id)s] %(name)s: %(message)s")
        )
    handler.addFilter(_ContextFilter())
    root.handlers = [handler]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    """Log with structured extra fields that land in the JSON payload."""
    logger.log(level, msg, extra={"extra_fields": fields})


async def fire_alert(title: str, detail: dict[str, Any]) -> None:
    """Log an alert at ERROR and optionally POST it to a webhook (Slack/Discord)."""
    logger = get_logger("alert")
    log_event(logger, logging.ERROR, title, **detail)
    if not settings.ALERT_WEBHOOK:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                settings.ALERT_WEBHOOK,
                json={"text": f":rotating_light: {title}", "detail": detail},
            )
    except Exception:  # never let alerting crash the caller
        logger.exception("alert webhook failed")
