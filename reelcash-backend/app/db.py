"""Persistence layer.

Two interchangeable backends behind one async API:

* ``MemoryDB``   — process-local dicts, used when ``DATABASE_URL`` is unset.
                   Perfect for demos, tests and local dev.
* ``PostgresDB`` — asyncpg-backed, schema in ``swara_schema.sql``.

The rest of the app only ever talks to the module-level ``db`` object.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from .config import settings
from .observability import get_logger

logger = get_logger("db")

VALID_STATUSES = {
    "queued", "scraping", "scripting", "voiceover", "rendering",
    "publishing", "live", "retrying", "failed", "dead_letter",
}
PIPELINE_STEPS = ["scrape", "script", "voiceover", "render", "publish"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# In-memory backend
# --------------------------------------------------------------------------- #
class MemoryDB:
    """Thread-safe, process-local store mirroring the Postgres schema."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.videos: dict[str, dict] = {}
        self.links: dict[str, dict] = {}          # keyed by code
        self.clicks: list[dict] = []
        self.checkpoints: dict[tuple[str, str], dict] = {}
        self.dead_letter: dict[str, dict] = {}
        self.earnings_sync: list[dict] = []

    async def connect(self) -> None:
        logger.info("using in-memory database (no DATABASE_URL set)")

    async def close(self) -> None:
        pass

    async def healthcheck(self) -> bool:
        return True

    # --- videos ---------------------------------------------------------- #
    async def create_video(self, product_url: str, platform: str) -> dict:
        vid = _new_id()
        row = {
            "id": vid,
            "product_url": product_url,
            "platform": platform,
            "status": "queued",
            "title": None,
            "video_url": None,
            "thumbnail_url": None,
            "views": 0,
            "error": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._lock:
            self.videos[vid] = row
        return dict(row)

    async def get_video(self, video_id: str) -> Optional[dict]:
        with self._lock:
            row = self.videos.get(video_id)
            return dict(row) if row else None

    async def list_videos(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = sorted(self.videos.values(), key=lambda r: r["created_at"], reverse=True)
            return [dict(r) for r in rows[:limit]]

    async def update_video(self, video_id: str, **fields: Any) -> Optional[dict]:
        if "status" in fields and fields["status"] not in VALID_STATUSES:
            raise ValueError(f"invalid status {fields['status']!r}")
        with self._lock:
            row = self.videos.get(video_id)
            if not row:
                return None
            row.update(fields)
            row["updated_at"] = _now()
            return dict(row)

    async def delete_video(self, video_id: str) -> bool:
        with self._lock:
            existed = self.videos.pop(video_id, None) is not None
            # cascade: drop the video's link + its clicks
            codes = [c for c, l in self.links.items() if l["video_id"] == video_id]
            for code in codes:
                self.links.pop(code, None)
                self.clicks = [c for c in self.clicks if c["code"] != code]
            self.checkpoints = {k: v for k, v in self.checkpoints.items() if k[0] != video_id}
            return existed

    # --- checkpoints ----------------------------------------------------- #
    async def save_checkpoint(self, video_id: str, step: str, output: dict) -> None:
        with self._lock:
            self.checkpoints[(video_id, step)] = {
                "video_id": video_id, "step": step,
                "output": output, "created_at": _now(),
            }

    async def get_checkpoint(self, video_id: str, step: str) -> Optional[dict]:
        with self._lock:
            cp = self.checkpoints.get((video_id, step))
            return dict(cp["output"]) if cp else None

    # --- links ----------------------------------------------------------- #
    async def create_link(self, video_id: str, code: str, destination: str) -> dict:
        row = {
            "code": code, "video_id": video_id, "destination": destination,
            "created_at": _now(), "updated_at": _now(),
        }
        with self._lock:
            self.links[code] = row
        return dict(row)

    async def get_link(self, code: str) -> Optional[dict]:
        with self._lock:
            row = self.links.get(code)
            return dict(row) if row else None

    async def repoint_link(self, code: str, destination: str) -> Optional[dict]:
        with self._lock:
            row = self.links.get(code)
            if not row:
                return None
            row["destination"] = destination
            row["updated_at"] = _now()
            return dict(row)

    async def list_links(self) -> list[dict]:
        with self._lock:
            out = []
            for code, link in self.links.items():
                clicks = sum(1 for c in self.clicks if c["code"] == code)
                video = self.videos.get(link["video_id"], {})
                earnings = sum(
                    (e["amount"] for e in self.earnings_sync if e["video_id"] == link["video_id"]),
                    Decimal("0"),
                )
                out.append({
                    **link,
                    "title": video.get("title"),
                    "platform": video.get("platform"),
                    "clicks": clicks,
                    "earnings": earnings,
                })
            return sorted(out, key=lambda r: r["created_at"], reverse=True)

    async def log_click(self, code: str, ip: str | None, user_agent: str | None,
                        referer: str | None) -> None:
        with self._lock:
            self.clicks.append({
                "id": _new_id(), "code": code, "ip": ip,
                "user_agent": user_agent, "referer": referer, "created_at": _now(),
            })

    # --- dead letter ----------------------------------------------------- #
    async def add_dead_letter(self, video_id: str | None, reason: str,
                             last_step: str | None, payload: dict) -> dict:
        row = {
            "id": _new_id(), "video_id": video_id, "reason": reason,
            "last_step": last_step, "payload": payload,
            "replayed": False, "created_at": _now(),
        }
        with self._lock:
            self.dead_letter[row["id"]] = row
        return dict(row)

    async def list_dead_letter(self) -> list[dict]:
        with self._lock:
            return sorted(
                (dict(r) for r in self.dead_letter.values()),
                key=lambda r: r["created_at"], reverse=True,
            )

    async def get_dead_letter(self, dl_id: str) -> Optional[dict]:
        with self._lock:
            row = self.dead_letter.get(dl_id)
            return dict(row) if row else None

    async def mark_dead_letter_replayed(self, dl_id: str) -> None:
        with self._lock:
            if dl_id in self.dead_letter:
                self.dead_letter[dl_id]["replayed"] = True

    # --- earnings -------------------------------------------------------- #
    async def add_earnings_sync(self, video_id: str, network: str,
                               amount: Decimal, clicks: int, currency: str = "INR") -> None:
        with self._lock:
            self.earnings_sync.append({
                "id": _new_id(), "video_id": video_id, "network": network,
                "amount": Decimal(str(amount)), "clicks": clicks,
                "currency": currency, "synced_at": _now(),
            })

    # --- stats ----------------------------------------------------------- #
    async def stats(self) -> dict:
        with self._lock:
            total_earnings = sum((e["amount"] for e in self.earnings_sync), Decimal("0"))
            total_clicks = len(self.clicks)
            total_views = sum(v.get("views", 0) for v in self.videos.values())
            live = sum(1 for v in self.videos.values() if v["status"] == "live")
            by_platform: dict[str, Decimal] = {}
            for e in self.earnings_sync:
                video = self.videos.get(e["video_id"], {})
                plat = video.get("platform", "unknown")
                by_platform[plat] = by_platform.get(plat, Decimal("0")) + e["amount"]
            # last 7 days earnings
            daily: dict[str, Decimal] = {}
            for e in self.earnings_sync:
                day = e["synced_at"].strftime("%Y-%m-%d")
                daily[day] = daily.get(day, Decimal("0")) + e["amount"]
            epc = (total_earnings / total_clicks) if total_clicks else Decimal("0")
            return {
                "total_earnings": total_earnings,
                "total_clicks": total_clicks,
                "total_views": total_views,
                "live_videos": live,
                "total_videos": len(self.videos),
                "epc": epc.quantize(Decimal("0.01")) if total_clicks else Decimal("0"),
                "by_platform": {k: v for k, v in by_platform.items()},
                "daily_earnings": daily,
            }


# --------------------------------------------------------------------------- #
# Postgres backend (asyncpg). Mirrors the same async interface as MemoryDB.
# --------------------------------------------------------------------------- #
class PostgresDB:  # pragma: no cover - exercised only with a live database
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool = None

    async def connect(self) -> None:
        import asyncpg

        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)
        await self._ensure_schema()
        logger.info("connected to postgres")

    async def _ensure_schema(self) -> None:
        import os

        schema_path = os.path.join(os.path.dirname(__file__), "..", "swara_schema.sql")
        if os.path.exists(schema_path):
            with open(schema_path) as f:
                ddl = f.read()
            async with self.pool.acquire() as con:
                await con.execute(ddl)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def healthcheck(self) -> bool:
        async with self.pool.acquire() as con:
            return (await con.fetchval("SELECT 1")) == 1

    async def create_video(self, product_url: str, platform: str) -> dict:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                """INSERT INTO videos (product_url, platform, status)
                   VALUES ($1, $2, 'queued') RETURNING *""",
                product_url, platform,
            )
            return dict(row)

    async def get_video(self, video_id: str) -> Optional[dict]:
        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM videos WHERE id = $1", video_id)
            return dict(row) if row else None

    async def list_videos(self, limit: int = 100) -> list[dict]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT * FROM videos ORDER BY created_at DESC LIMIT $1", limit
            )
            return [dict(r) for r in rows]

    async def update_video(self, video_id: str, **fields: Any) -> Optional[dict]:
        if not fields:
            return await self.get_video(video_id)
        if "status" in fields and fields["status"] not in VALID_STATUSES:
            raise ValueError(f"invalid status {fields['status']!r}")
        cols = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                f"UPDATE videos SET {cols}, updated_at = now() WHERE id = $1 RETURNING *",
                video_id, *fields.values(),
            )
            return dict(row) if row else None

    async def delete_video(self, video_id: str) -> bool:
        async with self.pool.acquire() as con:
            res = await con.execute("DELETE FROM videos WHERE id = $1", video_id)
            return res.endswith("1")

    async def save_checkpoint(self, video_id: str, step: str, output: dict) -> None:
        import json

        async with self.pool.acquire() as con:
            await con.execute(
                """INSERT INTO checkpoints (video_id, step, output)
                   VALUES ($1, $2, $3::jsonb)
                   ON CONFLICT (video_id, step)
                   DO UPDATE SET output = EXCLUDED.output, created_at = now()""",
                video_id, step, json.dumps(output),
            )

    async def get_checkpoint(self, video_id: str, step: str) -> Optional[dict]:
        import json

        async with self.pool.acquire() as con:
            val = await con.fetchval(
                "SELECT output FROM checkpoints WHERE video_id = $1 AND step = $2",
                video_id, step,
            )
            if val is None:
                return None
            return json.loads(val) if isinstance(val, str) else dict(val)

    async def create_link(self, video_id: str, code: str, destination: str) -> dict:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                """INSERT INTO links (code, video_id, destination)
                   VALUES ($1, $2, $3) RETURNING *""",
                code, video_id, destination,
            )
            return dict(row)

    async def get_link(self, code: str) -> Optional[dict]:
        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM links WHERE code = $1", code)
            return dict(row) if row else None

    async def repoint_link(self, code: str, destination: str) -> Optional[dict]:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "UPDATE links SET destination = $2, updated_at = now() WHERE code = $1 RETURNING *",
                code, destination,
            )
            return dict(row) if row else None

    async def list_links(self) -> list[dict]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                """SELECT l.*, v.title, v.platform,
                          COALESCE(cc.clicks, 0) AS clicks,
                          COALESCE(ec.earnings, 0) AS earnings
                   FROM links l
                   JOIN videos v ON v.id = l.video_id
                   LEFT JOIN (SELECT code, count(*) clicks FROM clicks GROUP BY code) cc
                          ON cc.code = l.code
                   LEFT JOIN (SELECT video_id, sum(amount) earnings FROM earnings_sync
                              GROUP BY video_id) ec ON ec.video_id = l.video_id
                   ORDER BY l.created_at DESC"""
            )
            return [dict(r) for r in rows]

    async def log_click(self, code, ip, user_agent, referer) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                """INSERT INTO clicks (code, ip, user_agent, referer)
                   VALUES ($1, $2, $3, $4)""",
                code, ip, user_agent, referer,
            )

    async def add_dead_letter(self, video_id, reason, last_step, payload) -> dict:
        import json

        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                """INSERT INTO dead_letter (video_id, reason, last_step, payload)
                   VALUES ($1, $2, $3, $4::jsonb) RETURNING *""",
                video_id, reason, last_step, json.dumps(payload),
            )
            return dict(row)

    async def list_dead_letter(self) -> list[dict]:
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT * FROM dead_letter ORDER BY created_at DESC")
            return [dict(r) for r in rows]

    async def get_dead_letter(self, dl_id: str) -> Optional[dict]:
        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM dead_letter WHERE id = $1", dl_id)
            return dict(row) if row else None

    async def mark_dead_letter_replayed(self, dl_id: str) -> None:
        async with self.pool.acquire() as con:
            await con.execute("UPDATE dead_letter SET replayed = true WHERE id = $1", dl_id)

    async def add_earnings_sync(self, video_id, network, amount, clicks, currency="INR") -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                """INSERT INTO earnings_sync (video_id, network, amount, clicks, currency)
                   VALUES ($1, $2, $3, $4, $5)""",
                video_id, network, Decimal(str(amount)), clicks, currency,
            )

    async def stats(self) -> dict:
        async with self.pool.acquire() as con:
            total_earnings = await con.fetchval("SELECT COALESCE(sum(amount),0) FROM earnings_sync")
            total_clicks = await con.fetchval("SELECT count(*) FROM clicks")
            total_views = await con.fetchval("SELECT COALESCE(sum(views),0) FROM videos")
            live = await con.fetchval("SELECT count(*) FROM videos WHERE status='live'")
            total_videos = await con.fetchval("SELECT count(*) FROM videos")
            by_plat = await con.fetch(
                """SELECT v.platform, sum(e.amount) amt FROM earnings_sync e
                   JOIN videos v ON v.id = e.video_id GROUP BY v.platform"""
            )
            daily = await con.fetch(
                """SELECT to_char(synced_at::date,'YYYY-MM-DD') d, sum(amount) amt
                   FROM earnings_sync WHERE synced_at > now() - interval '7 days'
                   GROUP BY d ORDER BY d"""
            )
            epc = (Decimal(total_earnings) / total_clicks) if total_clicks else Decimal("0")
            return {
                "total_earnings": Decimal(total_earnings),
                "total_clicks": total_clicks,
                "total_views": total_views,
                "live_videos": live,
                "total_videos": total_videos,
                "epc": epc.quantize(Decimal("0.01")) if total_clicks else Decimal("0"),
                "by_platform": {r["platform"]: r["amt"] for r in by_plat},
                "daily_earnings": {r["d"]: r["amt"] for r in daily},
            }


# Module-level singleton selected at import time.
db: MemoryDB | PostgresDB
if settings.use_memory_db:
    db = MemoryDB()
else:
    db = PostgresDB(settings.DATABASE_URL)
