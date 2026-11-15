# HTTP API

The app talks to a JSON API under `/api`. Sessions use an HttpOnly cookie. Every write request (`POST` or `PATCH`) must also send the header `X-Requested-With: vikrikavach`, which blocks cross-site form posts.

In development, interactive docs are at `/api/docs`. They are hidden in production; the OpenAPI document stays available at `/api/openapi.json`.

## Public

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness and database check: `{"ok": true, "ai": false, "storage": "s3"}` |
| GET | `/api/reference` | Crops, APMCs, price markets, complaint categories, and whether AI slip reading is on |
| POST | `/api/auth/otp/request` | `{phone}` sends a login code (5 per hour per number) |
| POST | `/api/auth/otp/verify` | `{phone, code}` sets the session and creates the farmer account on first login |
| POST | `/api/auth/staff/login` | `{username, password}` for officers and admins |
| POST | `/api/auth/logout` | Clears the session |

## Any logged-in user

| Method | Path | Purpose |
|---|---|---|
| GET / PATCH | `/api/me` | Read or update your profile (name, village, district, language) |
| GET | `/api/notifications` | The latest 30 notifications |
| POST | `/api/notifications/read` | Mark all as read |
| GET | `/api/traders/lookup?apmc_code=&licence_no=` | Look up a licence in the register |
| GET | `/api/prices/day?crop=&market=&day=` | The MSAMB price used for comparison |
| GET | `/api/sales/{id}` | A sale with its findings, evidence, payments and complaint (your own, or in an officer's APMC) |
| GET | `/api/evidence/{id}` | Download an evidence file |
| GET | `/api/complaints` | Your complaints, or your APMC's for officers |
| GET | `/api/complaints/{id}/pack` | Printable HTML evidence pack |

## Farmer

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/slips/read` | Multipart `file`: AI reads the slip and returns fields to fill the form. Nothing is stored. |
| POST | `/api/sales` | Record a sale and get the checks back |
| GET | `/api/sales` | Your sales, with checks |
| POST | `/api/sales/{id}/evidence` | Multipart `kind` + `file` (JPG, PNG, WebP or PDF, ≤ 10 MB) |
| POST | `/api/sales/{id}/payments` | `{kind: received \| cheque_bounced \| promised, amount, on_date, note}` |
| POST | `/api/sales/{id}/complaint` | `{categories[], description}` |

## APMC officer or admin

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/officer/dashboard` | Totals, per-trader patterns and flags, open complaints |
| GET | `/api/officer/complaints/{id}` | Complaint with the full sale |
| PATCH | `/api/officer/complaints/{id}` | `{status: under_review \| resolved \| rejected, officer_note}`. Notifies the farmer. |
| GET | `/api/officer/traders` | The licence register |
| POST | `/api/officer/traders` | Add or update a register entry (officers, for their own APMC) |

Officers see only their own APMC. Admins see every APMC.
