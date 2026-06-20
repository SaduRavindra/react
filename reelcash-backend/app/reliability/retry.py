"""Retry with exponential backoff + jitter, and the error taxonomy.

Two error classes drive retry decisions:

* ``TransientError``  — worth retrying (429, 5xx, timeouts, network blips).
* ``PermanentError``  — never retry (bad input, auth failure, 4xx that won't
                        change). Fails fast to the dead-letter path.

Unknown exceptions are treated as transient up to ``max_attempts`` so a
surprise still gets a few chances before dead-lettering.
"""
from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable, TypeVar

from ..observability import get_logger, log_event
import logging

logger = get_logger("retry")

T = TypeVar("T")


class TransientError(Exception):
    """A temporary failure; retrying may succeed."""


class PermanentError(Exception):
    """A non-recoverable failure; do not retry."""


def classify_http_status(status: int) -> type[Exception]:
    """Map an HTTP status to an error class."""
    if status == 429 or 500 <= status < 600:
        return TransientError
    if 400 <= status < 500:
        return PermanentError
    return TransientError


async def with_retry(
    func: Callable[[], Awaitable[T]],
    *,
    name: str = "op",
    max_attempts: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    jitter: float = 0.3,
) -> T:
    """Run ``func`` with exponential backoff + jitter.

    ``PermanentError`` short-circuits immediately. Everything else is retried
    up to ``max_attempts``; the final failure is re-raised.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await func()
        except PermanentError as exc:
            log_event(logger, logging.ERROR, "permanent failure, not retrying",
                      op=name, attempt=attempt, error=str(exc))
            raise
        except Exception as exc:  # transient or unknown
            if attempt >= max_attempts:
                log_event(logger, logging.ERROR, "exhausted retries",
                          op=name, attempts=attempt, error=str(exc))
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay * jitter)
            log_event(logger, logging.WARNING, "retrying after transient error",
                      op=name, attempt=attempt, next_delay=round(delay, 2), error=str(exc))
            await asyncio.sleep(delay)
