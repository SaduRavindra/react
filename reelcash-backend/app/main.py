"""FastAPI service: all HTTP endpoints for Swara Affiliates.

Data endpoints sit behind a bearer token (when DASHBOARD_TOKEN is set). The
public redirect ``/go/{code}`` and ``/health`` are open. The in-process queue
worker starts on app startup in demo/single-instance mode.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, field_validator

from .auth import require_token, require_worker_secret
from .config import settings
from .db import db
from .observability import configure_logging, get_logger, set_trace_id
from .pipeline import earnings, links
from .pipeline.runner import process_job
from .reliability import queue as queue_mod

configure_logging()
logger = get_logger("api")

VALID_PLATFORMS = {"youtube", "instagram", "pinterest", "telegram"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    queue_mod.set_processor(process_job)
    await queue_mod.queue.start()
    if queue_mod._fallback is not queue_mod.queue:
        await queue_mod._fallback.start()  # fallback worker for cloud-backend demos
    logger.info("swara api started")
    yield
    await queue_mod.queue.stop()
    await db.close()


app = FastAPI(title="Swara Affiliates API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",")] if settings.ALLOWED_ORIGINS else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# JSON encoding: Decimals → float, datetimes handled by FastAPI.
# --------------------------------------------------------------------------- #
def _jsonable(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class GenerateRequest(BaseModel):
    product_url: str
    platform: str = "telegram"

    @field_validator("platform")
    @classmethod
    def _platform_ok(cls, v: str) -> str:
        if v not in VALID_PLATFORMS:
            raise ValueError(f"platform must be one of {sorted(VALID_PLATFORMS)}")
        return v

    @field_validator("product_url")
    @classmethod
    def _url_ok(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("product_url must be an http(s) URL")
        return v


class RepointRequest(BaseModel):
    destination: str

    @field_validator("destination")
    @classmethod
    def _dest_ok(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("destination must be an http(s) URL")
        return v


# --------------------------------------------------------------------------- #
# Video endpoints
# --------------------------------------------------------------------------- #
@app.post("/videos/generate", dependencies=[Depends(require_token)])
async def generate_video(body: GenerateRequest):
    video = await db.create_video(body.product_url, body.platform)
    set_trace_id(video["id"])
    await queue_mod.queue.enqueue(video["id"])
    return _jsonable(video)


@app.get("/videos", dependencies=[Depends(require_token)])
async def list_videos():
    return _jsonable(await db.list_videos())


@app.get("/videos/{video_id}", dependencies=[Depends(require_token)])
async def get_video(video_id: str):
    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(404, "video not found")
    return _jsonable(video)


@app.delete("/videos/{video_id}", dependencies=[Depends(require_token)])
async def delete_video(video_id: str):
    ok = await db.delete_video(video_id)
    if not ok:
        raise HTTPException(404, "video not found")
    return {"deleted": True, "id": video_id}


# --------------------------------------------------------------------------- #
# Stats & earnings
# --------------------------------------------------------------------------- #
@app.get("/stats", dependencies=[Depends(require_token)])
async def stats():
    return _jsonable(await db.stats())


@app.post("/sync/earnings", dependencies=[Depends(require_token)])
async def sync_earnings():
    return _jsonable(await earnings.sync_earnings())


# --------------------------------------------------------------------------- #
# Dead-letter
# --------------------------------------------------------------------------- #
@app.get("/dead-letter", dependencies=[Depends(require_token)])
async def list_dead_letter():
    return _jsonable(await db.list_dead_letter())


@app.post("/dead-letter/{dl_id}/replay", dependencies=[Depends(require_token)])
async def replay_dead_letter(dl_id: str):
    dl = await db.get_dead_letter(dl_id)
    if not dl:
        raise HTTPException(404, "dead-letter entry not found")
    if not dl.get("video_id"):
        raise HTTPException(400, "dead-letter entry has no video to resume")
    await db.mark_dead_letter_replayed(dl_id)
    await queue_mod.replay(dl["video_id"])
    return {"replaying": True, "video_id": dl["video_id"]}


# --------------------------------------------------------------------------- #
# Links
# --------------------------------------------------------------------------- #
@app.get("/links", dependencies=[Depends(require_token)])
async def list_links():
    return _jsonable(await db.list_links())


@app.patch("/links/{code}", dependencies=[Depends(require_token)])
async def repoint_link(code: str, body: RepointRequest):
    link = await links.repoint(code, body.destination)
    if not link:
        raise HTTPException(404, "link not found")
    return _jsonable(link)


@app.get("/go/{code}")
async def go(code: str, request: Request):
    destination = await links.resolve(code)
    if not destination:
        raise HTTPException(404, "unknown link")
    await links.record_click(
        code,
        request.client.host if request.client else None,
        request.headers.get("user-agent"),
        request.headers.get("referer"),
    )
    return RedirectResponse(destination, status_code=302)


# --------------------------------------------------------------------------- #
# Worker callback (durable queue backends post here)
# --------------------------------------------------------------------------- #
@app.post("/internal/process")
async def internal_process(
    request: Request,
    x_worker_secret: Optional[str] = Header(default=None),
):
    require_worker_secret(x_worker_secret)
    body = await request.json()
    video_id = body.get("video_id")
    if not video_id:
        raise HTTPException(400, "video_id required")
    await process_job(video_id)
    return {"processed": video_id}


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@app.get("/health")
async def health():
    try:
        db_ok = await db.healthcheck()
    except Exception:
        db_ok = False
    code = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse({"status": "ok" if db_ok else "degraded", "db": db_ok}, status_code=code)
