"""Cloaked, repointable, trackable links.

Flow: raw URL → append associate tag → wrap in a short cloaked code →
publish the cloaked code → viewer hits ``/go/{code}`` → click is logged →
302 to the tagged destination.

Repointing changes one ``destination`` row and every published video that used
that code instantly redirects to the new target — no video edits needed.
"""
from __future__ import annotations

import secrets
import string

from ..config import settings
from ..db import db
from .affiliate import apply_affiliate_tag

_ALPHABET = string.ascii_lowercase + string.digits


def _mint_code(length: int = 7) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


async def mint_link(video_id: str, raw_url: str) -> dict:
    """Create a cloaked link for a video, tagging the raw URL first."""
    destination = apply_affiliate_tag(raw_url)
    # Retry on the astronomically unlikely code collision.
    for _ in range(5):
        code = _mint_code()
        if await db.get_link(code) is None:
            link = await db.create_link(video_id, code, destination)
            link["short_url"] = cloaked_url(code)
            return link
    raise RuntimeError("could not mint a unique link code")


def cloaked_url(code: str) -> str:
    domain = settings.LINK_DOMAIN.rstrip("/")
    return f"https://{domain}/go/{code}"


async def resolve(code: str) -> str | None:
    """Return the destination for a code, or None if unknown."""
    link = await db.get_link(code)
    return link["destination"] if link else None


async def record_click(code: str, ip: str | None, user_agent: str | None,
                       referer: str | None) -> None:
    await db.log_click(code, ip, user_agent, referer)


async def repoint(code: str, new_raw_url: str) -> dict | None:
    """Repoint a link to a new (re-tagged) destination."""
    destination = apply_affiliate_tag(new_raw_url)
    link = await db.repoint_link(code, destination)
    if link:
        link["short_url"] = cloaked_url(code)
    return link
