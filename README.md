# Swara Affiliates

Automated affiliate-marketing video studio. **Product URL in → published
affiliate video out**, with a cloaked trackable link and a live earnings
dashboard. Built for the Indian market (rupee earnings, Amazon.in + Flipkart
scraping; publishes to YouTube Shorts and Instagram Reels).

**Live dashboard (demo mode):** https://saduravindra.github.io/react/

## Contents

| Path | What |
|------|------|
| [`reelcash-backend/`](./reelcash-backend) | FastAPI backend, pipeline, reliability core, schema, tests |
| [`swara_affiliates_dashboard.html`](./swara_affiliates_dashboard.html) | Single-file dashboard (demo + live modes) |
| [`Swara_Affiliates_Project.md`](./Swara_Affiliates_Project.md) | Project spec |
| [`TODO.md`](./TODO.md) | Build status / remaining work |

## Run the demo (no credentials needed)

```bash
cd reelcash-backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `swara_affiliates_dashboard.html` in a browser (it defaults to demo mode).
To go live, set `API_BASE`/`API_TOKEN` in the HTML and the matching env vars on
the backend — see [`reelcash-backend/DEPLOY.md`](./reelcash-backend/DEPLOY.md).

## Tests

```bash
cd reelcash-backend
python -m tests.test_reliability
```
