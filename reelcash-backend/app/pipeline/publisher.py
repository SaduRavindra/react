"""Step 5 — Publish to the chosen platform with the cloaked link.

v1 supports two platforms: **YouTube Shorts** and **Instagram Reels**. The
cloaked affiliate link goes in the description / caption. Both are stubbed
pending OAuth tokens; each publisher returns a public post URL.
"""
from __future__ import annotations

from ..config import settings
from ..observability import get_logger
from ..reliability.breaker import guard
from ..reliability.retry import PermanentError, classify_http_status, with_retry

logger = get_logger("publisher")


def build_caption(script: dict, link: str) -> str:
    """Assemble description/caption text: hook, CTA, link, hashtags."""
    hook = script.get("hook", "")
    cta = script.get("cta", "")
    hashtags = " ".join(script.get("hashtags", []))
    parts = [p for p in (hook, cta, f"👉 {link}", hashtags) if p]
    return "\n\n".join(parts)


async def publish(platform: str, video_url: str, script: dict, link: str,
                  title: str | None = None) -> dict:
    caption = build_caption(script, link)
    publishers = {
        "youtube": _publish_youtube,
        "instagram": _publish_instagram,
    }
    fn = publishers.get(platform)
    if fn is None:
        raise PermanentError(f"unsupported platform: {platform}")

    async def _do() -> dict:
        return await fn(video_url, caption, link, title or script.get("hook", "Swara"))

    return await guard("publisher").call(lambda: with_retry(_do, name=f"publish_{platform}"))


# --------------------------------------------------------------------------- #
async def _publish_youtube(video_url: str, caption: str, link: str, title: str) -> dict:
    # Needs OAuth token + resumable upload of the rendered MP4. Stubbed for v1.
    logger.warning("YouTube publish stubbed (needs OAuth)")
    return {"post_url": "https://youtube.com/shorts/STUB", "_stub": True}


async def _publish_instagram(video_url: str, caption: str, link: str, title: str) -> dict:
    # Needs a Graph API token + media container publish flow. Stubbed for v1.
    logger.warning("Instagram publish stubbed (needs Graph API token)")
    return {"post_url": "https://instagram.com/reel/STUB", "_stub": True}
