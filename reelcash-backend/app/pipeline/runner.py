"""Pipeline orchestrator: the 5 checkpointed steps.

scrape → script → voiceover → render → publish

Each step runs through ``run_step`` so a completed step is never re-executed on
resume — the headline guarantee that a render failure doesn't re-pay for the
scrape, Claude and ElevenLabs calls. The runner advances the video's status,
times the whole job, and lets exceptions bubble to the queue's dead-letter path.
"""
from __future__ import annotations

import logging
import time

from ..db import db
from ..observability import get_logger, log_event, set_trace_id
from ..reliability.checkpoint import run_step
from . import links, publisher, scraper, script_writer, video_assembler, voiceover

logger = get_logger("runner")


async def process_job(video_id: str) -> None:
    """Run (or resume) the full pipeline for one video."""
    set_trace_id(video_id)
    video = await db.get_video(video_id)
    if not video:
        logger.error("process_job: unknown video %s", video_id)
        return

    started = time.monotonic()
    log_event(logger, logging.INFO, "pipeline start",
              product_url=video["product_url"], platform=video["platform"])

    # 1. Scrape
    await db.update_video(video_id, status="scraping")
    product = await run_step(video_id, "scrape", lambda: scraper.scrape(video["product_url"]))
    if product.get("title"):
        await db.update_video(video_id, title=product["title"])

    # 2. Script (expensive — checkpointed)
    await db.update_video(video_id, status="scripting")
    script = await run_step(video_id, "script", lambda: script_writer.write_script(product))

    # 3. Voiceover (paid — checkpointed)
    await db.update_video(video_id, status="voiceover")
    vo = await run_step(
        video_id, "voiceover",
        lambda: voiceover.synthesize(video_id, script.get("narration", "")),
    )

    # 4. Render
    await db.update_video(video_id, status="rendering")
    rendered = await run_step(
        video_id, "render",
        lambda: video_assembler.render(video_id, script, vo, product.get("images", [])),
    )
    await db.update_video(
        video_id,
        video_url=rendered.get("video_url"),
        thumbnail_url=rendered.get("thumbnail_url"),
    )

    # 5. Publish — mint the cloaked link, then post.
    await db.update_video(video_id, status="publishing")

    async def _publish_step() -> dict:
        link = await links.mint_link(video_id, video["product_url"])
        result = await publisher.publish(
            video["platform"], rendered.get("video_url"), script,
            link["short_url"], title=product.get("title"),
        )
        return {"code": link["code"], "short_url": link["short_url"], **result}

    published = await run_step(video_id, "publish", _publish_step)

    await db.update_video(video_id, status="live", error=None)
    elapsed = round(time.monotonic() - started, 2)
    log_event(logger, logging.INFO, "pipeline complete",
              elapsed_s=elapsed, post_url=published.get("post_url"),
              code=published.get("code"))
