"""Step 5 — Publish to the chosen platform with the cloaked link.

Telegram is the recommended first channel for India: the video and a tappable
"Buy now" button sit in the same message. YouTube / Instagram / Pinterest are
stubbed pending OAuth tokens. Each publisher returns a public post URL.
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
        "telegram": _publish_telegram,
        "youtube": _publish_youtube,
        "instagram": _publish_instagram,
        "pinterest": _publish_pinterest,
    }
    fn = publishers.get(platform)
    if fn is None:
        raise PermanentError(f"unsupported platform: {platform}")

    async def _do() -> dict:
        return await fn(video_url, caption, link, title or script.get("hook", "Swara"))

    return await guard("publisher").call(lambda: with_retry(_do, name=f"publish_{platform}"))


# --------------------------------------------------------------------------- #
async def _publish_telegram(video_url: str, caption: str, link: str, title: str) -> dict:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHANNEL:
        logger.warning("Telegram not configured — stub publish")
        return {"post_url": f"https://t.me/{settings.TELEGRAM_CHANNEL or 'channel'}", "_stub": True}

    import httpx  # pragma: no cover - needs token

    api = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendVideo"
    payload = {
        "chat_id": settings.TELEGRAM_CHANNEL,
        "video": video_url,
        "caption": caption,
        "reply_markup": {"inline_keyboard": [[{"text": "🛒 Buy now", "url": link}]]},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(api, json=payload)
        if resp.status_code >= 400:
            raise classify_http_status(resp.status_code)(
                f"telegram {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
    chat = settings.TELEGRAM_CHANNEL.lstrip("@")
    msg_id = data.get("result", {}).get("message_id", "")
    return {"post_url": f"https://t.me/{chat}/{msg_id}".rstrip("/")}


async def _publish_youtube(video_url: str, caption: str, link: str, title: str) -> dict:
    # Needs OAuth token + resumable upload of the rendered MP4. Stubbed for v1.
    logger.warning("YouTube publish stubbed (needs OAuth)")
    return {"post_url": "https://youtube.com/shorts/STUB", "_stub": True}


async def _publish_instagram(video_url: str, caption: str, link: str, title: str) -> dict:
    logger.warning("Instagram publish stubbed (needs Graph API token)")
    return {"post_url": "https://instagram.com/reel/STUB", "_stub": True}


async def _publish_pinterest(video_url: str, caption: str, link: str, title: str) -> dict:
    logger.warning("Pinterest publish stubbed (needs API token)")
    return {"post_url": "https://pinterest.com/pin/STUB", "_stub": True}
