-- Swara Affiliates — PostgreSQL schema
-- Money is NUMERIC(12,2); IDs are UUIDs; status/platform are enums;
-- foreign keys cascade on delete. Safe to run repeatedly (IF NOT EXISTS).

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- --- enums ---------------------------------------------------------------- --
DO $$ BEGIN
    CREATE TYPE video_status AS ENUM (
        'queued','scraping','scripting','voiceover','rendering',
        'publishing','live','retrying','failed','dead_letter'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE platform AS ENUM ('youtube','instagram','pinterest','telegram');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- --- videos (the hub) ----------------------------------------------------- --
CREATE TABLE IF NOT EXISTS videos (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_url   TEXT NOT NULL,
    platform      platform NOT NULL,
    status        video_status NOT NULL DEFAULT 'queued',
    title         TEXT,
    video_url     TEXT,
    thumbnail_url TEXT,
    views         BIGINT NOT NULL DEFAULT 0,
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at DESC);

-- --- links (1:1 with videos, repointable) --------------------------------- --
CREATE TABLE IF NOT EXISTS links (
    code        TEXT PRIMARY KEY,
    video_id    UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    destination TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_links_video ON links(video_id);

-- --- clicks (N:1 with links) ---------------------------------------------- --
CREATE TABLE IF NOT EXISTS clicks (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code       TEXT NOT NULL REFERENCES links(code) ON DELETE CASCADE,
    ip         INET,
    user_agent TEXT,
    referer    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_clicks_code ON clicks(code);
CREATE INDEX IF NOT EXISTS idx_clicks_created ON clicks(created_at);

-- --- checkpoints (per-step resume) ---------------------------------------- --
CREATE TABLE IF NOT EXISTS checkpoints (
    video_id   UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    step       TEXT NOT NULL,
    output     JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (video_id, step)
);

-- --- dead_letter (permanently failed jobs) -------------------------------- --
CREATE TABLE IF NOT EXISTS dead_letter (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id   UUID REFERENCES videos(id) ON DELETE SET NULL,
    reason     TEXT NOT NULL,
    last_step  TEXT,
    payload    JSONB,
    replayed   BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --- earnings_sync (periodic snapshots per network) ----------------------- --
CREATE TABLE IF NOT EXISTS earnings_sync (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id  UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    network   TEXT NOT NULL,
    amount    NUMERIC(12,2) NOT NULL DEFAULT 0,
    clicks    INTEGER NOT NULL DEFAULT 0,
    currency  TEXT NOT NULL DEFAULT 'INR',
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_earnings_video ON earnings_sync(video_id);
CREATE INDEX IF NOT EXISTS idx_earnings_synced ON earnings_sync(synced_at);
