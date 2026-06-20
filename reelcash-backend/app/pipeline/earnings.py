"""Periodic earnings / analytics sync.

In v1 this simulates an Associates report pull: for each live video it derives
a plausible click + earnings snapshot and writes it to ``earnings_sync``. Wire
your real Amazon Associates report (or per-network API) into ``_fetch_network``.
"""
from __future__ import annotations

import random
from decimal import Decimal

from ..db import db
from ..observability import get_logger

logger = get_logger("earnings")


async def sync_earnings() -> dict:
    """Pull latest earnings for all live videos. Returns a small summary."""
    videos = await db.list_videos(limit=1000)
    synced = 0
    total = Decimal("0")
    for video in videos:
        if video["status"] != "live":
            continue
        network = _network_for(video)
        amount, clicks = await _fetch_network(video, network)
        if amount > 0 or clicks > 0:
            await db.add_earnings_sync(video["id"], network, amount, clicks)
            synced += 1
            total += amount
    logger.info("earnings sync complete: %d videos, ₹%s", synced, total)
    return {"videos_synced": synced, "total_added": total}


def _network_for(video: dict) -> str:
    url = (video.get("product_url") or "").lower()
    if "flipkart" in url:
        return "flipkart"
    return "amazon"


async def _fetch_network(video: dict, network: str):  # pragma: no cover - simulated
    """Stub: replace with a real report pull. Returns (amount, clicks)."""
    clicks = random.randint(0, 25)
    # ~3% conversion at an average ₹40 commission.
    conversions = max(0, int(clicks * random.uniform(0.0, 0.06)))
    amount = Decimal(conversions) * Decimal("40.00")
    return amount, clicks
