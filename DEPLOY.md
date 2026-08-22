# Deploy

Model is published. Repo is pushed. Two services left, both one-click.

## 1. Backend — Render

Dashboard → **New** → **Blueprint** → pick `koushiknagabhatla-ctrl/hackathon-project`.
It reads `render.yaml`. Then paste these in the service's **Environment** tab:

| Key | Value |
|---|---|
| `OPENWEATHER_API_KEY` | from your `.env` |
| `OPENAQ_API_KEY` | from your `.env` |
| `TOMTOM_API_KEY` | from your `.env` |
| `DATA_GOV_IN_API_KEY` | from your `.env` |
| `WINDY_WEBCAMS_API_KEY` | from your `.env` |
| `FAST2SMS_API_KEY` | from your `.env` |
| `MAPTILER_API_KEY` | from your `.env` |
| `AURALIS_ALLOWED_ORIGINS` | your Vercel URL, after step 2 |
| `AURALIS_API_TOKEN` | any long random string (see below) |

Copy the service URL, e.g. `https://auralis-api.onrender.com`.

**Free plan notes.** `ENABLE_LOCAL_LLM=false` — the 1.5B model needs ~3 GB RAM
and is not installed there. Chat still answers from live sources, which is the
path that carries every real reading anyway. SQLite sits on an ephemeral disk,
so it re-seeds on each deploy; attach a persistent disk to keep runtime data.
The instance also sleeps when idle, so the first request after a pause is slow.

## 2. Frontend — Vercel

Dashboard → **Add New** → **Project** → import the same repo.
`vercel.json` sets the build; leave Root Directory blank. Add:

| Key | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE` | the Render URL from step 1 |
| `NEXT_PUBLIC_MAPTILER_KEY` | from your `.env` |
| `NEXT_PUBLIC_TOMTOM_KEY` | from your `.env` |
| `NEXT_PUBLIC_PRINCIPAL` | `p_operator` |
| `NEXT_PUBLIC_MOCK_MODE` | `false` |

Then go back to Render and set `AURALIS_ALLOWED_ORIGINS` to the Vercel URL,
or the browser will be blocked by CORS.

## 3. Close the API

`AURALIS_API_TOKEN` is the one that matters. Without it, anyone who can reach
the URL can send `X-Auralis-Principal: p_admin` and act as an administrator —
that header selects a role, it does not prove one.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set it on Render. Every request must then carry `X-Auralis-Token`.

## Model

`nadvkjdv/auralis-ap-urban-intelligence` — public, no token needed to pull it.
To run it, install the extras and give the instance ≥ 4 GB RAM:

```bash
pip install -r services/api/requirements.txt -r services/api/requirements-ml.txt
```

Then set `ENABLE_LOCAL_LLM=true` and `AURALIS_LOCAL_MODEL_PATH` to the
downloaded snapshot.

## Verify

```bash
curl https://<render-url>/v1/health
curl -H "X-Auralis-Principal: p_operator" "https://<render-url>/v1/weather/live?lat=16.5062&lon=80.648"
```
