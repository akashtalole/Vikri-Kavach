# Fraud checks

Every check is plain code, so each finding can be explained and reproduced. There is no black-box score. Findings are sorted by severity, and the sale's risk level is the highest severity found.

| Check | Code | Severity | When it fires |
|---|---|---|---|
| Short weighing | `weight_gap` | high | The slip weight is lower than the farmer's weighbridge weight by more than the tolerance (default 0.5%). Shows the gap in quintals and the loss in ₹ at the sale rate. |
| | `no_own_weight` | info | No weighbridge weight was given. The farmer is reminded to add it. |
| Gross arithmetic | `gross_math` | high | Quantity × rate differs from the slip's gross amount by more than 1%. |
| Net arithmetic | `net_math` | high | Gross − deductions differs from the slip's net amount by more than 1%. |
| Deduction rules | `not_allowed_*`, `high_*` | high / medium | A deduction is not allowed, or is above the configured rate, under `charge_rules.json`. |
| Rate below range | `rate_below_min` | high | The rate is below the lowest MSAMB auction price at that market on that day. |
| Low rate | `rate_low` | medium | The rate is in the bottom quarter of the day's range. Quality can explain a low rate, and the message says so. |
| Rate fine | `rate_ok` | ok | The rate is within the normal part of the range. |
| No price data | `no_price` | info | MSAMB has no price for that market, crop and date. |
| Unregistered trader | `trader_unregistered` | medium | The licence is not in the APMC's register. |
| Licence suspended or cancelled | `trader_suspended`, `trader_cancelled` | high | The APMC register lists the licence as not active. |
| Bounced cheque | `cheque_bounced` | high | A bounced cheque was recorded for the sale. |
| Overdue | `payment_overdue` | high | Money is still unpaid after the due date. |
| Cash | `cash` | info | Payment was in cash. The farmer is reminded to keep the slip and to ask for bank or UPI payment. |
| Reused photo | `evidence_reused` | medium | The same file (by SHA-256) is attached to another sale. |

## Where the prices come from

A daily job reads the **MSAMB** (Maharashtra State Agricultural Marketing Board) price pages for 22 major crops, including onion, soybean, cotton, tur, gram, wheat and tomato. It stores the minimum, maximum and modal price for each market, variety and date.

A sale is compared with the price for the **same market, crop and date**, and the same variety when one is given.

## Tuning

| Setting | Default | Effect |
|---|---|---|
| `WEIGHT_TOLERANCE_PCT` | `0.5` | Weight gap allowed before `weight_gap` fires |
| `PAYMENT_DAYS_DEFAULT` | `1` | Due date when the slip gives none |
| `bhavsetu/src/bhavsetu/data/charge_rules.json` | no limits | Allowed deductions and maximum rates for each kind of deduction |
