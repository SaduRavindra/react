"""Central configuration, sourced from environment variables.

Everything has a sensible default so the service runs out of the box in
in-memory demo mode (no DATABASE_URL, no provider keys).
"""
from __future__ import annotations

import os

try:  # optional: load a local .env if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Settings:
    # Core
    DATABASE_URL = _get("DATABASE_URL")
    DASHBOARD_TOKEN = _get("DASHBOARD_TOKEN")
    ALLOWED_ORIGINS = _get("ALLOWED_ORIGINS", "*")

    # Claude
    ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL", "claude-opus-4-8")

    # ElevenLabs
    ELEVENLABS_API_KEY = _get("ELEVENLABS_API_KEY")
    ELEVENLABS_VOICE_ID = _get("ELEVENLABS_VOICE_ID")

    # Shotstack
    SHOTSTACK_API_KEY = _get("SHOTSTACK_API_KEY")
    SHOTSTACK_ENV = _get("SHOTSTACK_ENV", "stage")

    # Storage
    STORAGE_BACKEND = _get("STORAGE_BACKEND", "local")
    STORAGE_BUCKET = _get("STORAGE_BUCKET")
    STORAGE_LOCAL_DIR = _get("STORAGE_LOCAL_DIR", "./_storage")

    # Affiliate / links
    AMAZON_ASSOCIATE_TAG = _get("AMAZON_ASSOCIATE_TAG")
    LINK_DOMAIN = _get("LINK_DOMAIN", "swara.link")

    # Telegram
    TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHANNEL = _get("TELEGRAM_CHANNEL")

    # Queue / worker
    QUEUE_BACKEND = _get("QUEUE_BACKEND", "inproc")
    WORKER_SECRET = _get("WORKER_SECRET")

    # Observability
    LOG_FORMAT = _get("LOG_FORMAT", "json")
    LOG_LEVEL = _get("LOG_LEVEL", "INFO")
    ALERT_WEBHOOK = _get("ALERT_WEBHOOK")

    @property
    def use_memory_db(self) -> bool:
        return not self.DATABASE_URL


settings = Settings()
