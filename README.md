# Vikri Kavach (विक्री कवच): sale shield for APMC farmers

**Track:** Agriculture. Farmer income protection, market access and digital crop-loss assessment.

At an APMC (agricultural market yard), a farmer can lose money after the auction in five common ways:
- a short-weighing scale
- a rate written below the day's auction range
- extra or inflated deductions
- payment delayed for weeks
- a cheque that bounces

The farmer rarely has the records to prove any of it. Vikri Kavach is a mobile-first web app that:

1. **Records every sale in two minutes.** The farmer photographs the slip (*patti*), and AI fills in the form when an Anthropic key is configured. The farmer adds their own weighbridge weight.
2. **Checks the sale automatically, with plain explanations:**
   - **Weight:** the slip weight against the farmer's own weighbridge, with the loss in rupees.
   - **Rate:** against the real MSAMB auction range for that market, crop, variety and day.
   - **Arithmetic:** quantity × rate = gross, and gross − deductions = net.
   - **Deductions:** against the configured charge rules.
   - **Licence:** the trader's licence against the APMC's own register (active, suspended or cancelled).
   - **Payment:** overdue or bounced payments, plus any slip photo reused on another sale.
3. **Runs a payment clock.** A daily job marks unpaid sales overdue and notifies the farmer.
4. **Builds a printable complaint pack.** One tap files a complaint, and the APMC secretary gets the facts, the checks, the payments and timestamped photos with SHA-256 fingerprints.
5. **Gives APMC officers a dashboard.** It shows overdue money by trader, bounced cheques, repeated weight gaps and low-rate patterns, and a complaint queue with status updates that reach the farmer. Officers also maintain the licence register.

Fairness rule: trader status comes **only** from the APMC's official register. Complaints and patterns are leads for officers to verify, and are never shown to the public as a blacklist.

| Farmer: sale checks (phone) | APMC officer dashboard |
|---|---|
| ![Sale checks](docs/screenshots/03-sale-checks.png) | ![Officer dashboard](docs/screenshots/06-officer-dashboard.png) |

More screens are in [`docs/screenshots/`](docs/screenshots/):
- Marathi login
- new sale form
- my sales
- evidence pack
- complaint handling
- licence register
- farmer notification

## Architecture

```
Browser (React 19 + Vite + Tailwind 4, Marathi / English)
   │  same-origin cookie session (HttpOnly JWT) + CSRF header
   ▼
One container on port 8080 (gunicorn + uvicorn workers)
   ├─ FastAPI API (/api/*)  ── PostgreSQL (Amazon RDS)
   ├─ React app (static)     ── S3: evidence photos (private, SSE)
   └─ daily jobs thread      ── Amazon SNS: OTP SMS
         ├─ MSAMB prices for 22 crops (live msamb.com data, via the shared bhavsetu package)
         └─ overdue payments → notifications
```

- **Daily jobs on many containers.** Each daily job claims a unique `(job, date)` row, so it runs once per day however many containers are up. If a container dies mid-job, another takes the claim over after 30 minutes.
- **Startup with many workers.** Table creation and the demo seed run under a PostgreSQL advisory lock, so several workers or tasks can start at once.
- **Farmer login.** Phone OTP: codes are HMAC-hashed, limited to 5 per hour and 5 attempts, and expire after 10 minutes. **APMC staff login:** username and scrypt-hashed password. Officers see only their own APMC.
- **Uploads.** Type is checked by magic bytes (JPG, PNG, WebP, PDF), up to 10 MB.
- **Audit.** Every write is logged to an audit table.

## Run locally

With Docker (Postgres + app at http://localhost:8080; demo officer `demo-officer` / `demo-officer-pass`):

```bash
cd vikrikavach && docker compose up --build
```

Without Docker:

```bash
pip install ./bhavsetu "./vikrikavach/backend[dev]"
```

```bash
cd vikrikavach/frontend && npm ci && npm run build
```

```bash
cd vikrikavach/backend && STATIC_DIR=../frontend/dist uvicorn app.main:build --factory --port 8080
```

In dev mode (`OTP_MODE=dev`) the OTP is shown on screen. For frontend work, run `npm run dev` (it proxies `/api` to port 8080).

Tests: `cd vikrikavach/backend && pytest -q` (13 tests: auth, checks, payments, complaints, officer scope, uploads, jobs).

## Deploy to Amazon ECS Express Mode

ECS Express Mode turns one container image into a running Fargate service: an HTTPS load balancer, auto scaling, logs and a public URL, all from a single command. [`deploy/deploy.sh`](deploy/deploy.sh) does everything around it:

1. Builds the image and pushes it to ECR.
2. Creates a private, encrypted S3 bucket for evidence.
3. Stores `JWT_SECRET`, `DATABASE_URL` and the optional keys in Secrets Manager.
4. Creates the roles:
   - `ecsTaskExecutionRole`, allowed to read those secrets.
   - `ecsInfrastructureRoleForExpressServices`.
   - A task role allowed S3 read/write on the bucket and SNS publish.
5. Runs `create-express-gateway-service`, or `update-express-gateway-service` on later runs. It uses health check `/api/health`, 1 vCPU / 2 GB, and scales from 1 to 4 tasks on CPU.

You need an RDS PostgreSQL database reachable from the default VPC first. Then run:

```bash
export AWS_REGION=ap-south-1
```

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@your-db.xxxx.ap-south-1.rds.amazonaws.com:5432/vikrikavach'
```

```bash
export ANTHROPIC_API_KEY=...        # optional: AI slip reading
```

```bash
export DEMO_APMC_CODE=02190400 STAFF_PASSWORD='choose-a-strong-one'   # optional: demo officer for Lasalgaon
```

```bash
vikrikavach/deploy/deploy.sh
```

The script prints the service's `https://…` URL. For real APMCs, create officer accounts and load the official licence register:

```bash
vikrikavach create-staff --username lasalgaon-secretary --apmc-code 02190400
```

```bash
vikrikavach import-traders --apmc-code 02190400 register.csv   # licence_no,name,firm,status
```

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///var/vikrikavach.db` | PostgreSQL in production |
| `JWT_SECRET` | dev value | Required, 32+ characters, when `APP_ENV=production` |
| `APP_ENV` | `development` | `production` turns on secure cookies, SMS OTP and hides API docs |
| `OTP_MODE` | `dev` / `sns` | `sns` sends OTP by Amazon SNS SMS |
| `S3_BUCKET` | empty (local disk) | Evidence storage |
| `ENABLE_SCHEDULER` | `false` | Daily price import and overdue marking |
| `WEIGHT_TOLERANCE_PCT` | `0.5` | Weight gap allowed before flagging |
| `PAYMENT_DAYS_DEFAULT` | `1` | Due date when the slip gives none |
| `ANTHROPIC_API_KEY` | empty | Enables AI slip reading |
| `DEMO_APMC_CODE` + `STAFF_PASSWORD` | empty | Seeds `demo-officer` and three sample register entries |

## Verified

- Image built and run with 3 workers against PostgreSQL 17.
- Imported 2,933 live MSAMB price rows across 22 crops.
- Ran the full farmer → officer → farmer flow in Chromium with Playwright: OTP login, three sales, slip photo upload, bounced cheque, complaint, officer resolution, and the farmer notification.
- The screenshots come from that run.
