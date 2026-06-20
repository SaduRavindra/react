"""Step 3 — Convert narration to an MP3 with ElevenLabs, store it.

Checkpointed (paid step). Falls back to a tiny silent placeholder stored in the
configured backend when ELEVENLABS_API_KEY is unset, so the pipeline completes.
"""
from __future__ import annotations

from ..config import settings
from ..observability import get_logger
from ..reliability.breaker import guard
from ..reliability.retry import classify_http_status, with_retry
from . import storage

logger = get_logger("voiceover")


async def synthesize(video_id: str, narration: str) -> dict:
    if not narration.strip():
        narration = "Check out this amazing product."

    if not settings.ELEVENLABS_API_KEY or not settings.ELEVENLABS_VOICE_ID:
        logger.warning("ElevenLabs not configured — storing silent placeholder audio")
        url = await storage.upload_bytes(
            f"audio/{video_id}.mp3", _silent_mp3(), "audio/mpeg"
        )
        return {"audio_url": url, "duration_estimate": _estimate_seconds(narration), "_stub": True}

    async def _do() -> dict:
        audio = await _call_elevenlabs(narration)
        url = await storage.upload_bytes(f"audio/{video_id}.mp3", audio, "audio/mpeg")
        return {"audio_url": url, "duration_estimate": _estimate_seconds(narration)}

    return await guard("elevenlabs").call(lambda: with_retry(_do, name="elevenlabs_tts"))


def _estimate_seconds(text: str) -> float:
    # ~2.5 words/sec speaking rate.
    return round(max(1, len(text.split())) / 2.5, 1)


async def _call_elevenlabs(narration: str) -> bytes:  # pragma: no cover - needs key
    import httpx

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.ELEVENLABS_VOICE_ID}"
    headers = {"xi-api-key": settings.ELEVENLABS_API_KEY, "accept": "audio/mpeg"}
    payload = {
        "text": narration,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise classify_http_status(resp.status_code)(
                f"elevenlabs {resp.status_code}: {resp.text[:200]}"
            )
        return resp.content


def _silent_mp3() -> bytes:
    # Minimal valid-ish MP3 frame header + padding; enough as a placeholder.
    return b"\xff\xfb\x90\x00" + b"\x00" * 512
