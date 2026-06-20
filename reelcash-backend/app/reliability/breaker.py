"""Circuit breaker + token-bucket rate limiter, one pair per external API.

* **Circuit breaker** — after N consecutive failures the circuit opens and
  calls fail fast for a cooldown, so one flaky provider can't stall the queue.
  After the cooldown it goes half-open and a probe call decides open vs closed.
* **Token bucket** — caps call rate to stay inside provider quotas.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, TypeVar

from .retry import TransientError

T = TypeVar("T")


class CircuitOpenError(TransientError):
    """Raised when the circuit is open; treated as transient for retries."""


class CircuitBreaker:
    def __init__(self, name: str, *, fail_threshold: int = 5, cooldown: float = 30.0) -> None:
        self.name = name
        self.fail_threshold = fail_threshold
        self.cooldown = cooldown
        self._failures = 0
        self._state = "closed"  # closed | open | half_open
        self._opened_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state

    async def call(self, func: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            if self._state == "open":
                if time.monotonic() - self._opened_at >= self.cooldown:
                    self._state = "half_open"
                else:
                    raise CircuitOpenError(f"circuit {self.name} is open")

        try:
            result = await func()
        except Exception:
            await self._on_failure()
            raise
        await self._on_success()
        return result

    async def _on_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._state = "closed"

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._state == "half_open" or self._failures >= self.fail_threshold:
                self._state = "open"
                self._opened_at = time.monotonic()


class TokenBucket:
    """Classic token bucket: ``rate`` tokens/sec, up to ``capacity`` burst."""

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self.rate = rate
        self.capacity = capacity if capacity is not None else rate
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait = deficit / self.rate
            await asyncio.sleep(wait)


class GuardedAPI:
    """A breaker + rate limiter bundled for a single provider."""

    def __init__(self, name: str, *, rate: float = 5.0, capacity: float | None = None,
                 fail_threshold: int = 5, cooldown: float = 30.0) -> None:
        self.name = name
        self.breaker = CircuitBreaker(name, fail_threshold=fail_threshold, cooldown=cooldown)
        self.bucket = TokenBucket(rate, capacity)

    async def call(self, func: Callable[[], Awaitable[T]]) -> T:
        await self.bucket.acquire()
        return await self.breaker.call(func)


# One guard per external provider, shared process-wide.
guards: dict[str, GuardedAPI] = {
    "scraper": GuardedAPI("scraper", rate=2.0),
    "claude": GuardedAPI("claude", rate=2.0),
    "elevenlabs": GuardedAPI("elevenlabs", rate=2.0),
    "shotstack": GuardedAPI("shotstack", rate=2.0),
    "publisher": GuardedAPI("publisher", rate=3.0),
}


def guard(name: str) -> GuardedAPI:
    return guards.setdefault(name, GuardedAPI(name))
