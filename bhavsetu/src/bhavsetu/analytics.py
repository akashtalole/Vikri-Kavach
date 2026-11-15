"""Market intelligence computed from MSAMB prices: best net market, arrival pressure, trend, fair-price check,
and FPC opportunities. All deterministic, so every number shown can be traced to a price row."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from .catalog import apmc_for_market
from .store import Store

ROAD_FACTOR = 1.3  # straight-line to road distance, rough average for rural Maharashtra
FRESH_DAYS = 2  # a market's price counts as current if it is at most this many days older than the latest day


@dataclass
class Costs:
    """Farmer-side costs. Defaults are placeholders the farmer or FPC should replace with their own figures."""
    transport_per_qtl_km: float = 1.0
    fixed_charges_per_qtl: float = 0.0
    charges_pct: float = 0.0


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _current_rows(store: Store, commodity: str) -> tuple[date | None, list[dict]]:
    latest = store.latest_date(commodity)
    if not latest:
        return None, []
    since = latest - timedelta(days=FRESH_DAYS)
    rows = store.all("SELECT * FROM prices WHERE commodity_code = ? AND price_date >= ? AND modal_price > 0"
                     " ORDER BY price_date DESC", (commodity, since.isoformat()))
    newest: dict[tuple, dict] = {}
    for r in rows:
        newest.setdefault((r["market"], r["variety"]), r)
    return latest, list(newest.values())


def current_varieties(store: Store, commodity: str) -> list[str]:
    """Varieties reported for this crop in the current window, most frequent first ('' means not stated)."""
    _, rows = _current_rows(store, commodity)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["variety"]] = counts.get(r["variety"], 0) + 1
    return sorted(counts, key=lambda v: -counts[v])


def arrival_pressure(store: Store, row: dict, lookback_days: int = 30) -> dict | None:
    """Arrivals on this row's day compared with the same market's median over earlier days."""
    day = date.fromisoformat(row["price_date"])
    hist = [h for h in store.history(row["commodity_code"], row["market"], row["variety"],
                                     day - timedelta(days=lookback_days))
            if h["price_date"] < row["price_date"] and h["arrival"]]
    if len(hist) < 3 or not row["arrival"]:
        return None
    usual = statistics.median(h["arrival"] for h in hist)
    if usual <= 0:
        return None
    ratio = row["arrival"] / usual
    return {"ratio": round(ratio, 2), "usual_arrival": round(usual), "days_compared": len(hist),
            "level": "glut" if ratio >= 1.5 else "low" if ratio <= 0.6 else "normal"}


def trend(store: Store, row: dict, lookback_days: int = 30) -> dict | None:
    day = date.fromisoformat(row["price_date"])
    hist = [h["modal_price"] for h in store.history(row["commodity_code"], row["market"], row["variety"],
                                                     day - timedelta(days=lookback_days))
            if h["price_date"] < row["price_date"] and h["modal_price"]]
    if len(hist) < 3:
        return None
    base = statistics.mean(hist)
    return {"change_pct": round((row["modal_price"] - base) / base * 100, 1), "average_before": round(base),
            "days_compared": len(hist)}


def best_markets(store: Store, commodity: str, origin: tuple[float, float], quantity_qtl: float,
                 costs: Costs | None = None, max_km: float = 250, variety: str | None = None, limit: int = 10) -> dict:
    """Rank markets by expected net amount to the farmer after transport and charges."""
    costs = costs or Costs()
    latest, rows = _current_rows(store, commodity)
    options = []
    for r in rows:
        if variety is not None and r["variety"] != variety:
            continue
        apmc = apmc_for_market(r["market"])
        if not apmc or apmc.get("lat") is None:
            continue
        km = haversine_km(origin, (apmc["lat"], apmc["lon"])) * ROAD_FACTOR
        if km > max_km:
            continue
        per_qtl_cost = km * costs.transport_per_qtl_km + costs.fixed_charges_per_qtl + \
            r["modal_price"] * costs.charges_pct / 100
        net_per_qtl = r["modal_price"] - per_qtl_cost
        options.append({
            "market": r["market"], "variety": r["variety"], "district": apmc.get("district_en"),
            "price_date": r["price_date"], "min": r["min_price"], "max": r["max_price"], "modal": r["modal_price"],
            "arrival": r["arrival"], "distance_km": round(km), "cost_per_qtl": round(per_qtl_cost),
            "net_per_qtl": round(net_per_qtl), "net_total": round(net_per_qtl * quantity_qtl),
            "pressure": arrival_pressure(store, r), "trend": trend(store, r),
        })
    options.sort(key=lambda o: o["net_total"], reverse=True)
    nearest = min(options, key=lambda o: o["distance_km"]) if options else None
    for o in options:
        o["gain_vs_nearest"] = round(o["net_total"] - nearest["net_total"]) if nearest else 0
    return {"commodity": commodity, "latest_date": latest and latest.isoformat(), "quantity_qtl": quantity_qtl,
            "costs": costs.__dict__, "nearest": nearest, "options": options[:limit],
            "markets_considered": len(options),
            "note": "Modal price is the most common auction price that day; the price for a given lot depends on "
                    "its quality. Distances are straight-line x 1.3. Cost assumptions are editable."}


def fair_price_check(store: Store, commodity: str, market: str, day: date, price: float,
                     variety: str | None = None) -> dict:
    """Where a farmer's sale price sits in that day's auction range at that market."""
    rows = [r for r in store.day(commodity, day) if r["market"] == market and (variety is None or r["variety"] == variety)]
    if not rows:
        return {"found": False, "note": "No MSAMB price for this market, crop and date. Check the date and market."}
    r = rows[0]
    lo, hi, modal = r["min_price"], r["max_price"], r["modal_price"]
    position = (price - lo) / (hi - lo) if hi and lo is not None and hi > lo else None
    if price < lo:
        verdict = "below_day_minimum"
    elif position is not None and position < 0.25:
        verdict = "bottom_quarter"
    elif price >= modal:
        verdict = "at_or_above_modal"
    else:
        verdict = "below_modal"
    same_day = store.day(commodity, day)
    district = (apmc_for_market(market) or {}).get("district_en")
    district_modals = [x["modal_price"] for x in same_day
                       if district and (apmc_for_market(x["market"]) or {}).get("district_en") == district]
    return {"found": True, "market": market, "variety": r["variety"], "date": day.isoformat(), "price": price,
            "min": lo, "max": hi, "modal": modal, "arrival": r["arrival"],
            "position_in_range": None if position is None else round(position, 2), "verdict": verdict,
            "gap_to_modal_per_qtl": round(modal - price), "district": district,
            "district_median_modal": round(statistics.median(district_modals)) if district_modals else None,
            "state_median_modal": round(statistics.median(x["modal_price"] for x in same_day)),
            "note": "Lower prices can reflect quality or moisture. A price below the day's minimum, or repeatedly "
                    "in the bottom quarter, is worth raising with the APMC secretary."}


def fpc_opportunities(store: Store, commodity: str, origin: tuple[float, float], quantity_qtl: float,
                      costs: Costs | None = None, max_km: float = 400) -> dict:
    """For a pooled FPC lot: best net markets, plus markets with high prices and normal or low arrivals."""
    result = best_markets(store, commodity, origin, quantity_qtl, costs, max_km=max_km, limit=15)
    modals = [o["modal"] for o in result["options"]]
    hot = []
    if len(modals) >= 5:
        mu, sd = statistics.mean(modals), statistics.pstdev(modals)
        for o in result["options"]:
            z = (o["modal"] - mu) / sd if sd else 0
            if z >= 1 and (o["pressure"] is None or o["pressure"]["level"] != "glut"):
                hot.append({**o, "z_score": round(z, 2)})
    result["high_price_markets"] = hot
    return result


def district_facts(store: Store, district_en: str, commodities: list[str]) -> list[dict]:
    """Numeric facts for a district bulletin: one per crop with data in the district's markets."""
    facts = []
    for code in commodities:
        latest, rows = _current_rows(store, code)
        rows = [r for r in rows if (apmc_for_market(r["market"]) or {}).get("district_en") == district_en]
        if not rows:
            continue
        best = max(rows, key=lambda r: r["modal_price"])
        low = min(rows, key=lambda r: r["modal_price"])
        gluts = [r["market"] for r in rows if (arrival_pressure(store, r) or {}).get("level") == "glut"]
        trends = [t["change_pct"] for r in rows if (t := trend(store, r))]
        facts.append({"commodity_code": code, "date": latest.isoformat(), "markets": len(rows),
                      "highest_modal": round(best["modal_price"]), "highest_market": best["market"],
                      "lowest_modal": round(low["modal_price"]), "lowest_market": low["market"],
                      "average_change_pct": round(statistics.mean(trends), 1) if trends else None,
                      "glut_markets": gluts})
    return facts
