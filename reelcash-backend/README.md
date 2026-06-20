# Swara Affiliates — backend

Automated affiliate-marketing video studio. **Product URL in → published
affiliate video out**, with a cloaked trackable link and a live earnings
dashboard. Built for the Indian market (rupee earnings, Amazon.in + Flipkart
scraping, Telegram as a first-class channel).

## Quick start (in-memory demo)

```bash
cd reelcash-backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

With no `DATABASE_URL` and no provider keys, the service runs fully in-memory
with deterministic stub steps — every endpoint works and the 5-step pipeline
completes. Open `http://localhost:8000/health`, then:

```bash
curl -X POST localhost:8000/videos/generate \
  -H 'content-type: application/json' \
  -d '{"product_url":"https://www.amazon.in/dp/B0EXAMPLE","platform":"telegram"}'
```

Watch the job walk `queued → scraping → … → live` via `GET /videos/{id}`.

## The pipeline (5 checkpointed steps)

`scrape → script (Claude) → voiceover (ElevenLabs) → render (Shotstack) →
publish (YouTube/Instagram/Pinterest/Telegram)`

Each step saves a checkpoint, retries transient errors with backoff+jitter, and
is fronted by a circuit breaker + token-bucket rate limiter. A render failure
**resumes from render** — it never re-scrapes or re-calls the paid Claude /
ElevenLabs steps.

## Going live

Set the relevant env vars (see `.env.example`):

- `DATABASE_URL` — Postgres; tables auto-create from `swara_schema.sql`.
- `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID`,
  `SHOTSTACK_API_KEY` — the real providers (otherwise stubbed).
- `AMAZON_ASSOCIATE_TAG`, `LINK_DOMAIN` — affiliate tagging + cloaked links.
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHANNEL` — Telegram publishing.
- `DASHBOARD_TOKEN` — bearer token gating the data API.
- `QUEUE_BACKEND` (`inproc`/`cloudtasks`/`sqs`) + `WORKER_SECRET`.

Full step-by-step in [`DEPLOY.md`](./DEPLOY.md).

## Layout

```
app/
  main.py            FastAPI app + all endpoints
  config.py          env-driven settings
  db.py              Postgres (asyncpg) + in-memory fallback
  auth.py            bearer-token gate
  observability.py   JSON logs, trace ids, alert hook
  pipeline/          scraper, script_writer, voiceover, video_assembler,
                     publisher, links, affiliate, earnings, storage, runner
  reliability/       retry, checkpoint, breaker, queue
swara_schema.sql     full Postgres schema
```

## API

| Method | Path | Auth |
|--------|------|------|
| POST | `/videos/generate` | ✓ |
| GET | `/videos` · `/videos/{id}` | ✓ |
| DELETE | `/videos/{id}` | ✓ |
| GET | `/stats` | ✓ |
| POST | `/sync/earnings` | ✓ |
| GET | `/dead-letter` · POST `/dead-letter/{id}/replay` | ✓ |
| GET | `/links` · PATCH `/links/{code}` | ✓ |
| GET | `/go/{code}` | public (logs click, 302s) |
| POST | `/internal/process` | worker secret |
| GET | `/health` | public |

Auth: `Authorization: Bearer <DASHBOARD_TOKEN>` when that env var is set.
