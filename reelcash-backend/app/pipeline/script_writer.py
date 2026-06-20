"""Step 2 — Turn product data into a structured video script with Claude.

Expensive step → checkpointed by the runner so a later failure never re-calls
it. Output is a strict JSON object: hook, scenes (narration + caption), CTA,
hashtags. Falls back to a template when ANTHROPIC_API_KEY is unset.
"""
from __future__ import annotations

import json

from ..config import settings
from ..observability import get_logger
from ..reliability.breaker import guard
from ..reliability.retry import PermanentError, classify_http_status, with_retry

logger = get_logger("script_writer")

SYSTEM_PROMPT = (
    "You are a short-form affiliate video scriptwriter for the Indian market. "
    "Write punchy, honest, high-converting vertical-video scripts. Prices are in "
    "rupees. Return ONLY valid JSON, no prose."
)

USER_TEMPLATE = """Write a 30-second vertical affiliate video script for this product.

Product: {title}
Price: {price}
Rating: {rating}
Features:
{features}

Return JSON exactly in this shape:
{{
  "hook": "first 3-second attention grabber",
  "scenes": [
    {{"narration": "spoken line", "caption": "on-screen text"}}
  ],
  "cta": "closing call to action mentioning the link",
  "hashtags": ["#tag1", "#tag2"]
}}
Use 3-5 scenes. Keep total narration under 150 words."""


def _build_user_prompt(product: dict) -> str:
    features = "\n".join(f"- {f}" for f in product.get("features", [])) or "- (none listed)"
    return USER_TEMPLATE.format(
        title=product.get("title", "Product"),
        price=product.get("price", "N/A"),
        rating=product.get("rating", "N/A"),
        features=features,
    )


def _validate_script(data: dict) -> dict:
    if not isinstance(data, dict) or "scenes" not in data or not data["scenes"]:
        raise PermanentError("script JSON missing required 'scenes'")
    data.setdefault("hook", "")
    data.setdefault("cta", "Tap the link to grab yours!")
    data.setdefault("hashtags", [])
    # Flatten narration for the voiceover step.
    data["narration"] = " ".join(
        s.get("narration", "") for s in data["scenes"]
    ).strip()
    return data


async def write_script(product: dict) -> dict:
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY unset — using template script")
        return _template_script(product)

    async def _do() -> dict:
        return await _call_claude(product)

    return await guard("claude").call(lambda: with_retry(_do, name="claude_script"))


async def _call_claude(product: dict) -> dict:  # pragma: no cover - needs key
    import httpx

    payload = {
        "model": settings.ANTHROPIC_MODEL,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": _build_user_prompt(product)}],
    }
    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages", json=payload, headers=headers
        )
        if resp.status_code >= 400:
            raise classify_http_status(resp.status_code)(
                f"claude {resp.status_code}: {resp.text[:200]}"
            )
        body = resp.json()
    text = "".join(block.get("text", "") for block in body.get("content", []))
    try:
        data = json.loads(_extract_json(text))
    except json.JSONDecodeError as exc:
        raise PermanentError(f"claude returned non-JSON: {exc}")
    return _validate_script(data)


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise PermanentError("no JSON object in model output")
    return text[start : end + 1]


def _template_script(product: dict) -> dict:
    title = product.get("title", "this product")
    price = product.get("price", "")
    features = product.get("features", [])[:3]
    scenes = [{"narration": f"Looking for {title}? Watch this.",
               "caption": title}]
    for feat in features:
        scenes.append({"narration": feat, "caption": feat})
    scenes.append({"narration": f"And it's just {price}.", "caption": f"Only {price}"})
    return _validate_script({
        "hook": f"You need to see {title}!",
        "scenes": scenes,
        "cta": "Tap the link in the description to grab yours now!",
        "hashtags": ["#deals", "#amazonindia", "#shopping", "#review"],
    })
