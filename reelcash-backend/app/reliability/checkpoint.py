"""Per-step checkpointing for idempotent, resumable pipelines.

``run_step`` is the heart of the cost-saving guarantee: if a step already has
a saved checkpoint, its output is returned without re-executing — so a render
failure never re-calls Claude or ElevenLabs (the paid steps).
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from ..db import db
from ..observability import get_logger, log_event

logger = get_logger("checkpoint")


async def run_step(
    video_id: str,
    step: str,
    func: Callable[[], Awaitable[dict]],
    *,
    force: bool = False,
) -> dict:
    """Return a cached checkpoint if present, else run ``func`` and save it."""
    if not force:
        cached = await db.get_checkpoint(video_id, step)
        if cached is not None:
            log_event(logger, logging.INFO, "checkpoint hit, skipping step",
                      step=step, trace_id=video_id)
            return cached

    log_event(logger, logging.INFO, "running step", step=step, trace_id=video_id)
    output = await func()
    await db.save_checkpoint(video_id, step, output)
    return output


async def last_completed_step(video_id: str, steps: list[str]) -> str | None:
    """The latest step (in order) that has a checkpoint, for resume/replay."""
    latest = None
    for step in steps:
        if await db.get_checkpoint(video_id, step) is not None:
            latest = step
        else:
            break
    return latest
