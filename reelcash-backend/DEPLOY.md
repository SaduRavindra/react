# Deploy checklist — Swara Affiliates

## 0. Accounts you'll need
- Anthropic (Claude), ElevenLabs, Shotstack
- A cloud account (GCP Cloud Run **or** AWS ECS Fargate)
- Supabase (or Cloud SQL) for Postgres
- Amazon Associates (commission tag)
- A Telegram bot (BotFather) + a channel

## 1. Run locally in-memory
```bash
cd reelcash-backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Confirm `/health` is `ok` and a generate request walks to `live`.

## 2. Attach the database
- Create a Postgres instance; copy its connection string into `DATABASE_URL`.
- Tables auto-create on startup, or run `psql "$DATABASE_URL" -f swara_schema.sql`.
- Restart and confirm `/health` reports `"db": true`.

## 3. Add provider credentials
Set in your hosting env (see `.env.example`):
`ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`,
`SHOTSTACK_API_KEY` (`SHOTSTACK_ENV=stage` to test), `STORAGE_BACKEND` +
`STORAGE_BUCKET`, `AMAZON_ASSOCIATE_TAG`, `LINK_DOMAIN`.

## 4. Deploy the API
**Cloud Run:**
```bash
gcloud run deploy swara-api --source . \
  --region asia-south1 --allow-unauthenticated \
  --set-env-vars "DATABASE_URL=...,DASHBOARD_TOKEN=...,..."
```
**ECS Fargate:** build the `Dockerfile`, push to ECR, run a service behind an ALB.

## 5. Deploy the dashboard
- Edit `swara_affiliates_dashboard.html`: set `API_BASE` to the API URL and
  `API_TOKEN` to your `DASHBOARD_TOKEN`.
- Drop it on Vercel/Netlify (no build step).
- Set `ALLOWED_ORIGINS` on the API to the dashboard's origin.

## 6. Point a domain
- Map `LINK_DOMAIN` (e.g. `swara.link`) to the API so `/go/{code}` redirects work.

## 7. Background jobs & durable queue
- Add Cloud Scheduler → `POST /sync/earnings` (e.g. every 6h) with the bearer token.
- Switch `QUEUE_BACKEND=cloudtasks` (or `sqs`) and set `WORKER_SECRET`; wire the
  task target to `POST /internal/process` (see `reliability/queue.py`).

## 8. Lock it down
- Set `DASHBOARD_TOKEN` (and the matching `API_TOKEN` in the dashboard).
- Add a log-based alert on `jsonPayload.status="dead_letter"`.
- Optionally set `ALERT_WEBHOOK` for Slack/Discord dead-letter alerts.

## 9. Telegram first channel
- Create a bot via BotFather, get `TELEGRAM_BOT_TOKEN`.
- Add the bot as an admin of your channel; set `TELEGRAM_CHANNEL` (e.g. `@swaradeals`).
- Generate a video on the Telegram platform and confirm the post + Buy-now button.
