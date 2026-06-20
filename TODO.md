# Swara Affiliates — TODO

Automated affiliate-marketing video studio. Product URL in → published
affiliate video out, with a cloaked trackable link and a live earnings
dashboard.

Legend: `[x]` done · `[~]` scaffolded / stubbed (needs creds or live tuning) ·
`[ ]` not started.

---

## Phase 0 — Scaffold (this commit)

- [x] Repository layout (`reelcash-backend/`, dashboard, schema, spec doc)
- [x] `requirements.txt`, `Dockerfile`, `.env.example`
- [x] FastAPI app + all HTTP endpoints (`app/main.py`)
- [x] Bearer-token auth gate (`app/auth.py`)
- [x] JSON logging + trace IDs + alert hook (`app/observability.py`)
- [x] Postgres layer with in-memory dev fallback (`app/db.py`)
- [x] Full Postgres schema (`swara_schema.sql`)
- [x] Dashboard (demo + live modes) (`swara_affiliates_dashboard.html`)

## Reliability

- [x] Retry w/ exponential backoff + jitter, error classes (`reliability/retry.py`)
- [x] Per-step checkpoint + resume / idempotency (`reliability/checkpoint.py`)
- [x] Circuit breaker + token-bucket rate limiter (`reliability/breaker.py`)
- [x] Durable queue + dead-letter + replay (`reliability/queue.py`, `inproc` backend)
- [ ] Cloud Tasks queue backend
- [ ] SQS queue backend

## Pipeline (5 steps)

- [x] Orchestrator, checkpointed (`pipeline/runner.py`)
- [~] Scrape — Playwright + Amazon.in / Flipkart / generic profiles (`pipeline/scraper.py`)
      *(stub fallback when Playwright unavailable; selectors need live tuning)*
- [~] Script — Claude prompt → structured JSON (`pipeline/script_writer.py`)
      *(stub fallback when `ANTHROPIC_API_KEY` unset)*
- [~] Voiceover — ElevenLabs → audio in storage (`pipeline/voiceover.py`)
      *(stub fallback when key unset)*
- [~] Render — Shotstack 9:16 timeline → MP4 (`pipeline/video_assembler.py`)
      *(stub fallback when key unset)*
- [~] Publish — YouTube / Instagram / Pinterest / Telegram (`pipeline/publisher.py`)
      *(Telegram caption building done; live posting needs bot token)*

## Links & affiliate

- [x] Cloaked links: mint / redirect / repoint / click tracking (`pipeline/links.py`)
- [x] Associate-tag appending per network (`pipeline/affiliate.py`)

## Storage

- [~] S3 / GCS / local upload helper (`pipeline/storage.py`)
      *(local backend works; S3/GCS need boto3/gcs libs + creds)*

## Earnings & analytics

- [~] Scheduled earnings/analytics sync (`pipeline/earnings.py`)
      *(simulated sync; plug in real Associates report pull)*

---

## Needs credentials / live tuning

- [ ] Scraper selectors per store (markup drifts)
- [ ] Social OAuth tokens (YouTube / Instagram / Pinterest)
- [ ] Real earnings sync from Amazon Associates report
- [ ] Telegram live posting (bot token + channel)

## Later (roadmap)

- [ ] Multi-user / team accounts
- [ ] React Native companion
- [ ] Scheduled posting
- [ ] A/B test hooks, auto-retire underperformers
