"""Durable job queue with dead-letter + replay.

Backends:

* ``inproc`` — an asyncio worker task in the API process. Good for dev and
  single-instance deploys. Jobs survive within the process; on hard crash the
  durable backends (Cloud Tasks / SQS) are what you switch to in prod.
* ``cloudtasks`` / ``sqs`` — stubs that enqueue via an HTTP callback to
  ``/internal/process`` (wire up with your cloud SDK + ``WORKER_SECRET``).

A failed job (after the pipeline exhausts retries) is written to the
``dead_letter`` table and an alert fires; it can be replayed from the API,
which resumes from the last checkpoint.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from ..config import settings
from ..db import db
from ..observability import fire_alert, get_logger, log_event, set_trace_id
from .retry import PermanentError

logger = get_logger("queue")

# Set by main.py at startup to avoid an import cycle with the pipeline runner.
_processor: Callable[[str], Awaitable[None]] | None = None


def set_processor(fn: Callable[[str], Awaitable[None]]) -> None:
    global _processor
    _processor = fn


class InProcQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())
            logger.info("inproc queue worker started")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._worker = None

    async def enqueue(self, video_id: str) -> None:
        await self._queue.put(video_id)
        log_event(logger, logging.INFO, "job enqueued", trace_id=video_id)

    async def _run(self) -> None:
        while True:
            video_id = await self._queue.get()
            set_trace_id(video_id)
            try:
                if _processor is None:
                    raise RuntimeError("no job processor registered")
                await _processor(video_id)
            except Exception as exc:  # pipeline already retried internally
                await self._dead_letter(video_id, exc)
            finally:
                self._queue.task_done()

    async def _dead_letter(self, video_id: str, exc: Exception) -> None:
        reason = f"{type(exc).__name__}: {exc}"
        video = await db.get_video(video_id)
        last_step = None
        from .checkpoint import last_completed_step
        from ..db import PIPELINE_STEPS

        last_step = await last_completed_step(video_id, PIPELINE_STEPS)
        await db.update_video(video_id, status="dead_letter", error=reason)
        await db.add_dead_letter(video_id, reason, last_step,
                                 {"product_url": video.get("product_url") if video else None})
        await fire_alert("job dead-lettered",
                         {"trace_id": video_id, "reason": reason, "last_step": last_step})


class HttpCallbackQueue:
    """Cloud Tasks / SQS style: enqueue a task that POSTs /internal/process.

    This is a thin stub — wire the actual Cloud Tasks or SQS client here. The
    important contract is: the task eventually calls the processor with the
    ``WORKER_SECRET`` so retries and durability are handled by the cloud queue.
    """

    def __init__(self, backend: str) -> None:
        self.backend = backend

    async def start(self) -> None:
        logger.info("queue backend %s selected (HTTP callback stub)", self.backend)

    async def stop(self) -> None:
        pass

    async def enqueue(self, video_id: str) -> None:
        log_event(logger, logging.INFO, "enqueue via %s (stub) — falling back to inproc"
                  % self.backend, trace_id=video_id)
        # Fallback so the demo still processes jobs even with a cloud backend set.
        await _fallback.enqueue(video_id)


_fallback = InProcQueue()


def build_queue():
    if settings.QUEUE_BACKEND in ("cloudtasks", "sqs"):
        return HttpCallbackQueue(settings.QUEUE_BACKEND)
    return _fallback


queue = build_queue()


async def replay(video_id: str) -> None:
    """Re-enqueue a job; the runner resumes from its last checkpoint."""
    await db.update_video(video_id, status="queued", error=None)
    await queue.enqueue(video_id)
