"""Patti (APMC sale slip) audit: Claude reads the photo, plain arithmetic and configurable rules check it.

The model only transcribes. Every judgement (does it add up, is a deduction allowed, how does the rate compare with
that day's MSAMB range) is made by code below, so the result can be explained line by line.
"""

from __future__ import annotations

import base64
import io
import json
from datetime import date, datetime
from importlib import resources

from PIL import Image, UnidentifiedImageError

from .analytics import fair_price_check
from .catalog import MAIN_CROPS
from .llm import Claude
from .store import Store

TOLERANCE = 0.01  # 1% for rounding on slips

SCHEMA = {
    "type": "object",
    "properties": {
        "readable": {"type": "boolean"},
        "market": {"type": "string", "description": "APMC / market name as written, in Marathi if so written"},
        "sale_date": {"type": "string", "description": "YYYY-MM-DD, or empty if not legible"},
        "trader_or_agent": {"type": "string"},
        "commodity": {"type": "string"},
        "lines": {"type": "array", "items": {"type": "object", "properties": {
            "description": {"type": "string"},
            "quantity_qtl": {"type": "number", "description": "Net weight in quintals; convert kg to quintals"},
            "rate_per_qtl": {"type": "number"},
            "amount": {"type": "number"}},
            "required": ["description", "quantity_qtl", "rate_per_qtl", "amount"], "additionalProperties": False}},
        "gross_amount": {"type": "number"},
        "deductions": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string", "description": "As written, e.g. हमाली, तोलाई, आडत, वाहतूक, उचल"},
            "kind": {"type": "string", "enum": ["commission", "hamali", "weighing", "market_fee", "transport",
                                                "advance_recovery", "other"]},
            "amount": {"type": "number"}},
            "required": ["label", "kind", "amount"], "additionalProperties": False}},
        "net_paid": {"type": "number"},
        "payment_mode": {"type": "string", "enum": ["cash", "cheque", "bank_transfer", "upi", "not_stated"]},
        "illegible_parts": {"type": "string"},
    },
    "required": ["readable", "market", "sale_date", "trader_or_agent", "commodity", "lines", "gross_amount",
                 "deductions", "net_paid", "payment_mode", "illegible_parts"],
    "additionalProperties": False,
}

PROMPT = """This is a sale slip (patti) a farmer received at an agricultural market in Maharashtra. Transcribe it.
Copy numbers exactly as written; do not correct the slip's arithmetic. Convert kilograms to quintals (100 kg = 1
quintal) for quantity_qtl. If a value is missing or illegible, use 0 and mention it in illegible_parts. Classify each
deduction by its kind: आडत/कमिशन = commission, हमाली = hamali, तोलाई/तोलणी = weighing, बाजार फी/सेस = market_fee,
वाहतूक/भाडे = transport, उचल/ॲडव्हान्स = advance_recovery."""


def load_rules() -> dict:
    text = resources.files("bhavsetu").joinpath("data/charge_rules.json").read_text(encoding="utf-8")
    return json.loads(text)


def image_block(data: bytes) -> dict:
    if data[:4] == b"%PDF":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                               "data": base64.standard_b64encode(data).decode("ascii")}}
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("upload a photo (JPG/PNG) or PDF of the slip") from exc
    img.thumbnail((1800, 1800))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(buf.getvalue()).decode("ascii")}}


def read_slip(claude: Claude, data: bytes) -> dict:
    return claude.json([{"role": "user", "content": [image_block(data), {"type": "text", "text": PROMPT}]}],
                       SCHEMA, effort="medium")


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(1.0, TOLERANCE * max(abs(a), abs(b)))


def check_slip(slip: dict, rules: dict | None = None, store: Store | None = None,
               commodity_code: str | None = None) -> dict:
    """Deterministic checks on a transcribed slip. Returns findings with severity and plain explanations."""
    rules = rules if rules is not None else load_rules()
    findings: list[dict] = []

    def add(severity: str, code: str, message: str) -> None:
        findings.append({"severity": severity, "code": code, "message": message})

    if not slip.get("readable"):
        add("info", "unreadable", "The slip could not be read clearly. Retake the photo in good light, flat and whole.")
        return {"findings": findings, "summary": None}
    qty = sum(l["quantity_qtl"] for l in slip["lines"])
    for i, l in enumerate(slip["lines"], 1):
        if l["quantity_qtl"] and l["rate_per_qtl"] and not _close(l["quantity_qtl"] * l["rate_per_qtl"], l["amount"]):
            add("high", "line_math", f"Line {i}: {l['quantity_qtl']:g} qtl x Rs {l['rate_per_qtl']:g} = Rs "
                f"{l['quantity_qtl'] * l['rate_per_qtl']:,.0f}, but the slip shows Rs {l['amount']:,.0f}.")
    line_total = sum(l["amount"] for l in slip["lines"])
    gross = slip["gross_amount"] or line_total
    if slip["lines"] and slip["gross_amount"] and not _close(line_total, slip["gross_amount"]):
        add("high", "gross_math", f"Lines add up to Rs {line_total:,.0f}, but the gross amount shown is Rs "
            f"{slip['gross_amount']:,.0f}.")
    total_ded = sum(d["amount"] for d in slip["deductions"])
    if slip["net_paid"] and not _close(gross - total_ded, slip["net_paid"]):
        add("high", "net_math", f"Gross Rs {gross:,.0f} minus deductions Rs {total_ded:,.0f} = Rs "
            f"{gross - total_ded:,.0f}, but net paid is Rs {slip['net_paid']:,.0f}.")
    for d in slip["deductions"]:
        rule = rules.get("deductions", {}).get(d["kind"], {})
        if rule.get("charged_to_farmer") is False and d["amount"] > 0:
            add("high", f"not_allowed_{d['kind']}", f"'{d['label']}' (Rs {d['amount']:,.0f}) was deducted from the "
                f"farmer, but the configured rule says it is not chargeable to the seller. {rule.get('source', '')}".strip())
        limit_pct = rule.get("max_pct_of_gross")
        if limit_pct is not None and gross and d["amount"] / gross * 100 > limit_pct:
            add("medium", f"high_{d['kind']}", f"'{d['label']}' is {d['amount'] / gross * 100:.1f}% of the gross "
                f"amount; the configured limit is {limit_pct:g}%. {rule.get('source', '')}".strip())
        limit_qtl = rule.get("max_per_qtl")
        if limit_qtl is not None and qty and d["amount"] / qty > limit_qtl:
            add("medium", f"high_{d['kind']}", f"'{d['label']}' is Rs {d['amount'] / qty:,.1f} per quintal; the "
                f"configured limit is Rs {limit_qtl:g}. {rule.get('source', '')}".strip())
    if slip["payment_mode"] == "cash" and rules.get("flag_cash_payment"):
        add("info", "cash", "Paid in cash: keep this slip safe; ask for a bank payment next time so there is a record.")
    if gross and total_ded / gross > rules.get("flag_total_deductions_pct", 100) / 100:
        add("medium", "high_total", f"Total deductions are {total_ded / gross * 100:.1f}% of the gross amount.")
    market_check = None
    if store and commodity_code and slip["lines"] and slip.get("sale_date"):
        try:
            day = datetime.strptime(slip["sale_date"], "%Y-%m-%d").date()
            avg_rate = line_total / qty if qty else 0
            market_check = fair_price_check(store, commodity_code, slip["market"], day, avg_rate)
            if market_check.get("found") and market_check["verdict"] in ("below_day_minimum", "bottom_quarter"):
                add("medium", "low_rate", f"Average rate Rs {avg_rate:,.0f}/qtl was "
                    f"{'below the day minimum' if market_check['verdict'] == 'below_day_minimum' else 'in the bottom quarter'}"
                    f" at {slip['market']} that day (range Rs {market_check['min']:,.0f}-{market_check['max']:,.0f}, "
                    f"modal Rs {market_check['modal']:,.0f}).")
        except ValueError:
            pass
    if not any(f["severity"] in ("high", "medium") for f in findings):
        add("ok", "no_issue", "The slip adds up and no configured rule was broken.")
    order = {"high": 0, "medium": 1, "info": 2, "ok": 3}
    findings.sort(key=lambda f: order[f["severity"]])
    return {"findings": findings, "market_check": market_check,
            "summary": {"quantity_qtl": round(qty, 2), "gross": round(gross, 2), "deductions": round(total_ded, 2),
                        "deductions_pct": round(total_ded / gross * 100, 1) if gross else None,
                        "net_paid": slip["net_paid"], "average_rate": round(line_total / qty) if qty else None}}


def guess_commodity(name: str) -> str | None:
    name = (name or "").strip().lower()
    for code, (en, mr) in MAIN_CROPS.items():
        if name and (mr in name or name in mr or en.lower().split(" ")[0] in name):
            return code
    return None


def parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
