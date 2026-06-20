"""Step 4 — Render a 9:16 vertical MP4 with Shotstack.

Builds a timeline from the product images + scene captions + voiceover audio
and polls Shotstack until the render is done. Falls back to a stub MP4 URL when
SHOTSTACK_API_KEY is unset.
"""
from __future__ import annotations

import asyncio

from ..config import settings
from ..observability import get_logger
from ..reliability.breaker import guard
from ..reliability.retry import TransientError, classify_http_status, with_retry

logger = get_logger("video_assembler")

_BASE = {
    "stage": "https://api.shotstack.io/stage",
    "v1": "https://api.shotstack.io/v1",
}


def build_timeline(script: dict, voiceover: dict, images: list[str]) -> dict:
    """Assemble a Shotstack edit JSON: image clips + caption titles + audio."""
    scenes = script.get("scenes", [])
    per = max(2.0, round(voiceover.get("duration_estimate", 20) / max(1, len(scenes)), 1))
    clips = []
    start = 0.0
    for i, scene in enumerate(scenes):
        img = images[i % len(images)] if images else None
        if img:
            clips.append({
                "asset": {"type": "image", "src": img},
                "start": start, "length": per,
                "fit": "cover", "effect": "zoomIn",
            })
        clips.append({
            "asset": {"type": "title", "text": scene.get("caption", ""),
                      "style": "blockbuster", "size": "medium"},
            "start": start, "length": per,
        })
        start += per

    return {
        "timeline": {
            "background": "#000000",
            "soundtrack": {"src": voiceover.get("audio_url"), "effect": "fadeOut"},
            "tracks": [{"clips": clips}],
        },
        "output": {"format": "mp4", "size": {"width": 1080, "height": 1920}},
    }


async def render(video_id: str, script: dict, voiceover: dict, images: list[str]) -> dict:
    timeline = build_timeline(script, voiceover, images)

    if not settings.SHOTSTACK_API_KEY:
        logger.warning("SHOTSTACK_API_KEY unset — returning stub render URL")
        return {
            "video_url": f"https://cdn.example.com/renders/{video_id}.mp4",
            "thumbnail_url": (images[0] if images else None),
            "_stub": True,
        }

    async def _do() -> dict:
        render_id = await _submit(timeline)
        url = await _poll(render_id)
        return {
            "video_url": url,
            "thumbnail_url": (images[0] if images else None),
            "render_id": render_id,
        }

    return await guard("shotstack").call(lambda: with_retry(_do, name="shotstack_render"))


def _api_base() -> str:
    return _BASE.get(settings.SHOTSTACK_ENV, _BASE["stage"])


async def _submit(timeline: dict) -> str:  # pragma: no cover - needs key
    import httpx

    headers = {"x-api-key": settings.SHOTSTACK_API_KEY, "content-type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{_api_base()}/render", json=timeline, headers=headers)
        if resp.status_code >= 400:
            raise classify_http_status(resp.status_code)(
                f"shotstack submit {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()["response"]["id"]


async def _poll(render_id: str, *, max_polls: int = 40, interval: float = 5.0) -> str:  # pragma: no cover
    import httpx

    headers = {"x-api-key": settings.SHOTSTACK_API_KEY}
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(max_polls):
            resp = await client.get(f"{_api_base()}/render/{render_id}", headers=headers)
            data = resp.json()["response"]
            status = data["status"]
            if status == "done":
                return data["url"]
            if status == "failed":
                raise TransientError(f"shotstack render {render_id} failed")
            await asyncio.sleep(interval)
    raise TransientError(f"shotstack render {render_id} timed out")
