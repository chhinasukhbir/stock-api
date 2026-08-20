# Yahoo Finance Stock API

A small, self-contained FastAPI service that wraps [`yfinance`](https://github.com/ranaroussi/yfinance) to expose current price, historical price, and call option chain data for any stock ticker, sourced from Yahoo Finance. Ships as a Docker container so it can be deployed to any container host.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/stocks/{ticker}/price` | Latest price, previous close, change, change % |
| GET | `/stocks/{ticker}/history` | Historical OHLCV data. Query params: `period` (default `1mo`), `interval` (default `1d`), or `start`/`end` dates (`YYYY-MM-DD`) |
| GET | `/stocks/{ticker}/options` | List of available option expiry dates |
| GET | `/stocks/{ticker}/options/{expiry}/calls` | Call option chain for a specific expiry date (`YYYY-MM-DD`, must be one of the dates returned by `/options`) |

Interactive docs (Swagger UI) are auto-generated at `/docs` once the service is running, and machine-readable OpenAPI JSON at `/openapi.json`.

### Example requests

```bash
curl http://localhost:8000/stocks/AAPL/price
curl "http://localhost:8000/stocks/AAPL/history?period=6mo&interval=1d"
curl http://localhost:8000/stocks/AAPL/options
curl http://localhost:8000/stocks/AAPL/options/2026-09-19/calls
```

### Notes

- Ticker symbols are case-insensitive and normalized to uppercase.
- Responses are cached in memory for a short window (30s for price, 2-5 min for history/options) to reduce load on Yahoo Finance and lower the chance of being rate-limited. Cache is per-process and resets on restart; swap in Redis if you run multiple replicas and want a shared cache.
- Yahoo Finance is an unofficial/undocumented data source accessed via `yfinance`. It can occasionally rate-limit or change response shape upstream; if you see repeated failures, wait a bit or pin a specific `yfinance` version known to work.
- Only call options are exposed via `/options/{expiry}/calls`. `yfinance`'s `option_chain()` also returns a `puts` DataFrame if you want to add a `/options/{expiry}/puts` endpoint later — the code path is identical to the calls handler in `main.py`.

## Run locally

### With Docker (recommended)

```bash
docker build -t stock-api .
docker run -p 8000:8000 stock-api
```

Or with Docker Compose:

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`.

### Without Docker

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Deploying

This is a standard Dockerized web service listening on `$PORT` (defaults to `8000`), so it deploys to any container platform. A few common options:

**Render**
1. Push this project to a GitHub repo.
2. New → Web Service → connect the repo → Render auto-detects the `Dockerfile`.
3. No extra env vars needed. Deploy.

**Railway**
1. `railway init` in this folder, then `railway up` — Railway auto-detects the `Dockerfile` and injects `$PORT`.

**Fly.io**
1. `fly launch` in this folder (accept the detected Dockerfile config).
2. `fly deploy`.

**Google Cloud Run**
```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/stock-api
gcloud run deploy stock-api --image gcr.io/PROJECT_ID/stock-api --platform managed --port 8000 --allow-unauthenticated
```

**AWS (ECS/App Runner/EC2)**
- Build and push the image to ECR (`docker build`, `docker tag`, `docker push`), then point App Runner or an ECS service at it, or run the container directly on an EC2 host with `docker run`.

**Any generic VPS**
```bash
docker build -t stock-api .
docker run -d -p 8000:8000 --restart unless-stopped --name stock-api stock-api
```
Put it behind Nginx/Caddy for TLS if exposing it publicly.

## Testing note

This service was built and logic-tested against mocked Yahoo Finance responses (FastAPI's `TestClient` with a stubbed `yfinance.Ticker`) — the sandbox this was built in has an outbound network allowlist that does not include Yahoo Finance's domains, so a live call couldn't be made from there. All routing, parsing, rounding, and error-handling logic is verified correct. Once deployed to a normal host (Render, Railway, Fly.io, Cloud Run, a VPS, etc. — none of which have that restriction), it will reach Yahoo Finance directly. After deploying, sanity-check with:

```bash
curl https://<your-deployed-url>/stocks/AAPL/price
```

If that returns real price data, everything is working end-to-end.

## Project structure

```
stock-api/
├── main.py              # FastAPI app + all endpoints
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
└── README.md
```
