"""Bearer-token gate for the dashboard API.

When ``DASHBOARD_TOKEN`` is unset the API is open (handy for local dev). When
set, every protected endpoint requires ``Authorization: Bearer <token>``.
The public redirect and health check never use this dependency.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import settings


async def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = settings.DASHBOARD_TOKEN
    if not expected:
        return  # auth disabled

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")


def require_worker_secret(secret: str | None) -> None:
    expected = settings.WORKER_SECRET
    if not expected:
        return
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bad worker secret")
