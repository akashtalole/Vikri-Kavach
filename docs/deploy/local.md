# Run locally

## With Docker Compose

```bash
docker compose up --build
```

This starts PostgreSQL 17 and the app at <http://localhost:8080>. Login codes are shown on screen. The demo officer is `demo-officer` with password `demo-officer-pass`, for Lasalgaon. The scheduler imports live MSAMB prices on startup.

To try AI slip reading, set `ANTHROPIC_API_KEY` in your shell before running compose.

## Without Docker

```bash
pip install ./bhavsetu "./backend[dev]"
```

```bash
cd frontend && npm ci && npm run build && cd ..
```

```bash
cd backend && STATIC_DIR=../frontend/dist uvicorn app.main:build --factory --port 8080
```

Without `DATABASE_URL`, the app uses SQLite at `backend/var/vikrikavach.db`. To get prices, run `vikrikavach daily` once, or set `ENABLE_SCHEDULER=true`.

For frontend work, keep the backend running and use the Vite dev server, which proxies `/api` to port 8080:

```bash
cd frontend && npm run dev
```

## Tests

```bash
cd backend && pytest -q
```

```bash
pytest -q bhavsetu/tests
```

CI (`.github/workflows/ci.yml`) runs:
- both test suites
- a smoke test on PostgreSQL
- the frontend build
- shellcheck on the CloudShell scripts
- a Docker image health check
