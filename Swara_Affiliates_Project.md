# Swara Affiliates — Project Spec

An automated affiliate-marketing video studio. You paste a product link; the
system scrapes it, writes a script with Claude, generates a voiceover, renders a
vertical video, publishes it, and tracks clicks and earnings — all from one
dashboard.

**Product URL in → published affiliate video out, with a cloaked trackable link
and a live earnings dashboard.** Built for the Indian market: rupee earnings,
Amazon.in + Flipkart scraping, and publishing to YouTube Shorts and
Instagram Reels.

## Architecture

```
Dashboard (Vercel) ──HTTPS──► FastAPI service ──enqueue──► Durable queue
                                                              │
                                                              ▼
   Pipeline worker (checkpointed, retryable):
   scrape → script(Claude) → voiceover(11L) → render(Shotstack) → publish
                                     │ reads/writes
                                     ▼
                               PostgreSQL

   Public:  GET /go/{code}  →  logs click  →  302 redirect to product
```

## The 5-step pipeline

1. **Scrape** — Playwright loads the product page with a store-specific selector
   profile (Amazon.in / Flipkart / generic), extracts title, price, rating,
   features, images. Blocks fonts/media for speed.
2. **Script** — Claude turns product data into structured JSON (hook, scenes,
   CTA, hashtags). *Expensive → checkpointed.*
3. **Voiceover** — ElevenLabs → MP3 in storage. *Paid → checkpointed.*
4. **Render** — Shotstack builds a 9:16 vertical MP4.
5. **Publish** — mints a cloaked link, posts to the chosen platform
   (YouTube Shorts or Instagram Reels) with the link in the description / caption.

Statuses: `queued → scraping → scripting → voiceover → rendering → publishing →
live` (or `retrying` / `failed` / `dead_letter`).

## Reliability

| Mechanism | Protects against |
|-----------|------------------|
| Durable queue | Worker crash losing the job |
| Checkpoints + resume | Re-running already-paid steps |
| Retry w/ backoff + jitter | Transient API blips (429/5xx/timeouts) |
| Permanent vs transient classes | Wasting retries on bad input / auth |
| Circuit breakers (per API) | One flaky provider stalling the queue |
| Rate limiters (token bucket) | Blowing through API quotas |
| Dead-letter + replay | Silently dropping failed jobs |
| Health checks | Routing to a broken instance |

**Headline win:** a render failure resumes from render — it does *not* re-scrape
or re-call Claude/ElevenLabs, so retries cost nothing extra.

## Data model (6 tables)

`videos` (hub) · `links` (1:1, repointable) · `clicks` (N:1) ·
`checkpoints` (PK `video_id,step`) · `dead_letter` · `earnings_sync`.
Money is `NUMERIC(12,2)`; IDs are UUIDs; FKs cascade. DDL in
`reelcash-backend/swara_schema.sql`.

## Cloaked links

Published videos carry `swara.link/go/<code>`, not the raw Amazon URL. Cleaner
links convert better, you own the click data, and you can **repoint anytime** —
change one destination and every published video using that code redirects to
the new target (out of stock → switch to Flipkart, higher-commission program,
etc.) with zero video changes.

## Deliverables in this repo

| File | What it is |
|------|------------|
| `reelcash-backend/` | FastAPI backend + Dockerfile + README + DEPLOY.md + schema + tests |
| `swara_affiliates_dashboard.html` | Dashboard (demo + live modes) |
| `Swara_Affiliates_Project.md` | This document |
| `TODO.md` | Build status / remaining work |

See `reelcash-backend/README.md` to run it (in-memory demo needs no creds) and
`reelcash-backend/DEPLOY.md` for the full go-live checklist.
