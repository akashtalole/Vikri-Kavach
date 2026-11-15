# Architecture

```mermaid
flowchart TB
    subgraph Container["One container (port 8080, gunicorn + uvicorn workers)"]
        SPA[React 19 app<br/>static files]
        API[FastAPI<br/>/api/*]
        JOBS[Daily jobs thread]
    end
    Browser -->|cookie session + CSRF header| SPA & API
    API --> DB[(PostgreSQL)]
    API --> S3[(S3 evidence)]
    API --> SNS[SNS SMS]
    API -.optional.-> Claude[Claude API<br/>slip reading]
    JOBS --> DB
    JOBS --> MSAMB[msamb.com]
```

## Code layout

| Path | Contents |
|---|---|
| `backend/app/main.py` | API routes, authentication, the complaint pack, serving the static app |
| `backend/app/checks.py` | All fraud checks (see [Fraud checks](../product/checks.md)) |
| `backend/app/jobs.py` | Price import, overdue marking, daily scheduler with a claim on each job |
| `backend/app/models.py` | SQLAlchemy models |
| `backend/app/services.py` | S3 or disk storage, SNS or dev SMS, the Claude client |
| `backend/app/security.py` | Phone normalisation, scrypt passwords, HMAC-hashed OTPs, JWT |
| `backend/app/cli.py` | Admin command line |
| `bhavsetu/` | Market-data package (vendored): MSAMB client, APMC master list, slip reading and rules |
| `frontend/src/` | React pages, Marathi and English strings, API client |
| `cloudshell/` | AWS deployment and operations scripts |

## Data model

```mermaid
erDiagram
    USER ||--o{ SALE : records
    USER ||--o{ NOTIFICATION : receives
    TRADER ||--o{ SALE : "linked by licence"
    SALE ||--o{ EVIDENCE : has
    SALE ||--o{ PAYMENT_EVENT : has
    SALE ||--o| COMPLAINT : "may have"
    PRICE }o..o{ SALE : "compared by market, crop, date"
    USER { string role "farmer | officer | admin" string phone string apmc_code }
    TRADER { string apmc_code string licence_no string status "active | suspended | cancelled" }
    SALE { string reference float own_weight_qtl float slip_weight_qtl float rate_per_qtl json deductions float net_amount date payment_due string status }
    EVIDENCE { string kind string storage_key string sha256 }
    COMPLAINT { string reference json categories string status string officer_note }
    PRICE { string commodity_code string market string variety date price_date float min_price float modal_price float max_price }
```

Other tables:
- `otp_codes`: hashed login codes.
- `job_runs`: one row per job per day.
- `audit`: every write action.

## Running on several containers

- **Daily jobs.** Every task runs the scheduler thread, and each job first claims a unique `(job, date)` row. Only the task that wins the claim runs the job. If a task dies mid-job, its unfinished claim can be taken over after 30 minutes. A finished job is never repeated that day.
- **Startup.** Table creation and the demo seed run under PostgreSQL advisory locks, so workers and tasks can start at the same moment.
- **Sessions.** These are stateless signed cookies, so any task can serve any request.
