"""Fraud and risk checks on a recorded sale. Plain code: every finding can be explained and reproduced.

Checks:
- weight: the trader's slip weight against the farmer's own weighbridge weight (and bag count if given)
- rate: the rate against the day's MSAMB auction range at the same market
- arithmetic: quantity x rate = gross; gross - deductions = net
- deductions: against the configured charge rules (bhavsetu/data/charge_rules.json)
- licence: the trader against the APMC's own licence register
- payment: overdue, bounced cheques, cash without a record
- reused evidence: the same slip photo used on another sale
"""

from __future__ import annotations

from datetime import date

from bhavsetu.patti import check_slip, load_rules
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Evidence, Price, Sale


def _f(severity: str, code: str, message: str, **data) -> dict:
    return {"severity": severity, "code": code, "message": message, **({"data": data} if data else {})}


def day_price(db: Session, commodity: str, market: str, day: date, variety: str = "") -> Price | None:
    rows = db.scalars(select(Price).where(Price.commodity_code == commodity, Price.market == market,
                                          Price.price_date == day)).all()
    if not rows:
        return None
    same = [r for r in rows if r.variety == variety]
    return (same or rows)[0]


def check_sale(db: Session, sale: Sale, tolerance_pct: float, today: date) -> list[dict]:
    out: list[dict] = []

    # weight
    if sale.own_weight_qtl:
        gap = sale.own_weight_qtl - sale.slip_weight_qtl
        pct = gap / sale.own_weight_qtl * 100
        if pct > tolerance_pct:
            loss = gap * sale.rate_per_qtl
            out.append(_f("high", "weight_gap",
                          f"The slip shows {sale.slip_weight_qtl:g} qtl but your weighbridge showed "
                          f"{sale.own_weight_qtl:g} qtl: {gap:.2f} qtl ({pct:.1f}%) less, worth about Rs {loss:,.0f} "
                          f"at the sale rate.", gap_qtl=round(gap, 3), gap_pct=round(pct, 2), value=round(loss)))
    else:
        out.append(_f("info", "no_own_weight", "Add your own weighbridge weight to check the trader's scale."))

    # arithmetic
    expected_gross = sale.slip_weight_qtl * sale.rate_per_qtl
    if abs(expected_gross - sale.gross_amount) > max(1, 0.01 * expected_gross):
        out.append(_f("high", "gross_math", f"{sale.slip_weight_qtl:g} qtl x Rs {sale.rate_per_qtl:g} = Rs "
                      f"{expected_gross:,.0f}, but the slip's gross amount is Rs {sale.gross_amount:,.0f}."))
    total_ded = sum(float(d.get("amount") or 0) for d in sale.deductions)
    if abs(sale.gross_amount - total_ded - sale.net_amount) > max(1, 0.01 * sale.gross_amount):
        out.append(_f("high", "net_math", f"Gross Rs {sale.gross_amount:,.0f} minus deductions Rs {total_ded:,.0f} = "
                      f"Rs {sale.gross_amount - total_ded:,.0f}, but the slip's net amount is Rs {sale.net_amount:,.0f}."))

    # deductions against configured rules (reuses the BhavSetu patti rules engine)
    slip = {"readable": True, "market": sale.market_name, "sale_date": sale.sale_date.isoformat(),
            "lines": [{"description": "", "quantity_qtl": sale.slip_weight_qtl, "rate_per_qtl": sale.rate_per_qtl,
                       "amount": sale.gross_amount}],
            "gross_amount": sale.gross_amount, "deductions": sale.deductions, "net_paid": sale.net_amount,
            "payment_mode": sale.payment_mode}
    for f in check_slip(slip, load_rules())["findings"]:
        if f["code"].startswith(("not_allowed_", "high_")):
            out.append(f)

    # rate against the day's auction range
    p = day_price(db, sale.commodity_code, sale.market_name, sale.sale_date, sale.variety)
    if p and p.min_price and p.max_price and p.modal_price:
        if sale.rate_per_qtl < p.min_price:
            out.append(_f("high", "rate_below_min", f"Rate Rs {sale.rate_per_qtl:,.0f} is below the lowest auction "
                          f"price recorded at {sale.market_name} that day (Rs {p.min_price:,.0f}; modal Rs "
                          f"{p.modal_price:,.0f}).", min=p.min_price, modal=p.modal_price, max=p.max_price))
        elif p.max_price > p.min_price and (sale.rate_per_qtl - p.min_price) / (p.max_price - p.min_price) < 0.25:
            out.append(_f("medium", "rate_low", f"Rate Rs {sale.rate_per_qtl:,.0f} is in the bottom quarter of the "
                          f"day's range at {sale.market_name} (Rs {p.min_price:,.0f}-{p.max_price:,.0f}, modal Rs "
                          f"{p.modal_price:,.0f}). Lower rates can reflect quality.",
                          min=p.min_price, modal=p.modal_price, max=p.max_price))
        else:
            out.append(_f("ok", "rate_ok", f"Rate is within the normal part of the day's range (modal Rs "
                          f"{p.modal_price:,.0f}).", min=p.min_price, modal=p.modal_price, max=p.max_price))
    else:
        out.append(_f("info", "no_price", "No MSAMB price found for this market, crop and date to compare."))

    # licence register
    if sale.trader is None:
        out.append(_f("medium", "trader_unregistered", "This trader is not in the APMC's licence register here. "
                      "Ask the APMC office to confirm the licence before the next sale."))
    elif sale.trader.status != "active":
        out.append(_f("high", "trader_" + sale.trader.status, f"The APMC register lists this trader's licence as "
                      f"{sale.trader.status}. {sale.trader.status_note}".strip()))

    # payment
    bounced = [p for p in sale.payments if p.kind == "cheque_bounced"]
    if bounced:
        out.append(_f("high", "cheque_bounced", f"{len(bounced)} cheque(s) bounced for this sale."))
    outstanding = round(sale.net_amount - sale.amount_paid, 2)
    if outstanding > 0 and today > sale.payment_due:
        out.append(_f("high", "payment_overdue", f"Rs {outstanding:,.0f} is unpaid, {(today - sale.payment_due).days} "
                      f"day(s) after the due date ({sale.payment_due.isoformat()}).", outstanding=outstanding))
    if sale.payment_mode == "cash":
        out.append(_f("info", "cash", "Paid in cash: keep the slip. Ask for bank or UPI payment next time."))

    # reused evidence
    for e in sale.evidence:
        dup = db.scalar(select(func.count()).select_from(Evidence)
                        .where(Evidence.sha256 == e.sha256, Evidence.sale_id != sale.id))
        if dup:
            out.append(_f("medium", "evidence_reused", f"The same {e.kind} photo is attached to another sale."))

    order = {"high": 0, "medium": 1, "info": 2, "ok": 3}
    out.sort(key=lambda f: order[f["severity"]])
    return out


def risk_level(findings: list[dict]) -> str:
    sev = {f["severity"] for f in findings}
    return "high" if "high" in sev else "medium" if "medium" in sev else "low"
