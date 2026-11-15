"""Client for the Maharashtra State Agricultural Marketing Board (MSAMB) public price pages.

Reads what msamb.com shows publicly:
- the commodity list (codes and Marathi names) from the price page,
- the districts and APMCs (English and Marathi names) from the APMC profile page,
- one APMC's profile (address, PIN code, important commodities, facilities),
- commodity-wise daily prices across all APMCs for roughly the last week
  (market, variety, unit, arrivals, minimum, maximum and modal price).

The site needs a session cookie from the HTML page before its data calls answer, and it is a public
government service, so calls are spaced out and cached. Nothing here logs in or bypasses any control.
"""

from __future__ import annotations

import ast
import html
import re
import time
from dataclasses import dataclass
from datetime import date, datetime

import httpx

BASE = "https://www.msamb.com"
PRICE_PAGE = "/ApmcDetail/APMCPriceInformation"
PROFILE_PAGE = "/ApmcDetail/Profile"
USER_AGENT = "BhavSetu/0.1 (farmer price information; contact via repository)"

ROW = re.compile(
    r"<tr>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*"
    r"<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>\s*</tr>", re.S)
DATE_ROW = re.compile(r'<td colspan="7">\s*(\d{2}/\d{2}/\d{4})\s*</td>')
OPTION = re.compile(r'<option value="([^"]*)"[^>]*>([^<]+)</option>')


class MsambError(Exception):
    pass


@dataclass(frozen=True)
class PriceRow:
    price_date: date
    market: str
    variety: str
    unit: str
    arrival: float | None
    min_price: float | None
    max_price: float | None
    modal_price: float | None


def _num(text: str) -> float | None:
    text = text.strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_price_table(fragment: str) -> list[PriceRow]:
    """Parse the HTML rows returned by DataGridBind. Date header rows precede each day's market rows."""
    rows: list[PriceRow] = []
    current: date | None = None
    pos = 0
    events = sorted([(m.start(), "date", m) for m in DATE_ROW.finditer(fragment)]
                    + [(m.start(), "row", m) for m in ROW.finditer(fragment)], key=lambda e: e[0])
    for _, kind, m in events:
        if kind == "date":
            current = datetime.strptime(m.group(1), "%d/%m/%Y").date()
            continue
        if current is None:
            continue
        market, variety, unit, arrival, lo, hi, modal = (html.unescape(g).strip() for g in m.groups())
        variety = "" if variety in ("---", "-") else variety
        rows.append(PriceRow(current, market, variety, unit, _num(arrival), _num(lo), _num(hi), _num(modal)))
        pos += 1
    return rows


def _names(value, key: str) -> list[str]:
    """MSAMB returns some lists as Python-style text; turn them into sorted English names."""
    if not value:
        return []
    try:
        items = ast.literal_eval(value) if isinstance(value, str) else value
    except (ValueError, SyntaxError):
        return []
    return sorted({(i.get(key) or "").strip().title() for i in items if isinstance(i, dict) and (i.get(key) or "").strip()})


def parse_commodities(page_html: str) -> list[tuple[str, str]]:
    m = re.search(r'id="drpCommodities"[^>]*>(.*?)</select>', page_html, re.S)
    if not m:
        raise MsambError("commodity list not found on the price page")
    return [(code, html.unescape(name).strip()) for code, name in OPTION.findall(m.group(1)) if code]


class MsambClient:
    def __init__(self, http: httpx.Client | None = None, pause_seconds: float = 1.0):
        self.http = http or httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        self.pause = pause_seconds
        self._sessions: dict[str, bool] = {}
        self._last = 0.0

    def _wait(self) -> None:
        delay = self.pause - (time.monotonic() - self._last)
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def _page(self, path: str) -> str:
        self._wait()
        resp = self.http.get(BASE + path)
        if resp.status_code != 200:
            raise MsambError(f"{path}: HTTP {resp.status_code}")
        self._sessions[path] = True
        return resp.text

    def _xhr(self, page: str, path: str, params: dict | None = None, accept_json: bool = False) -> httpx.Response:
        if page not in self._sessions:
            self._page(page)
        self._wait()
        headers = {"X-Requested-With": "XMLHttpRequest", "Referer": BASE + page}
        if accept_json:
            headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
        resp = self.http.get(BASE + path, params=params, headers=headers)
        if resp.status_code != 200:
            raise MsambError(f"{path}: HTTP {resp.status_code}")
        return resp

    def commodities(self) -> list[tuple[str, str]]:
        return parse_commodities(self._page(PRICE_PAGE))

    def districts(self) -> list[dict]:
        data = self._xhr(PROFILE_PAGE, "/ApmcDetail/GetDistrictForAPMCProfile", accept_json=True).json()
        return [{"district_id": d["DistrictId"], "name_en": d["DistrictNameE"], "name_mr": d["DistrictNameM"],
                 "apmcs": [{"full_code": a["ApmcCode"], "name_en": a["ApmcNameE"], "name_mr": a["ApmcNameM"]}
                           for a in d.get("ApmcList") or []]} for d in data]

    def profile(self, full_code: str) -> dict:
        data = self._xhr(PROFILE_PAGE, "/ApmcDetail/ProfileDetail", {"apmcId": full_code}, accept_json=True).json()
        d = data[0] if isinstance(data, list) and data else data
        if not d:
            raise MsambError(f"no profile for {full_code}")
        # Keep institutional information only; office bearers' names and mobile numbers are not stored.
        return {"code": d.get("ApmcCode"), "full_code": d.get("ApmcFullCode"),
                "address_en": (d.get("AddressE") or "").strip(), "address_mr": (d.get("AddressM") or "").strip(),
                "pin_code": (d.get("PinCode") or "").strip(),
                "important_commodities": _names(d.get("ImpCommodityList"), "CommodityNameE"),
                "facilities": _names(d.get("FacilitiesInMarket"), "FacilityNameE"),
                "established": (d.get("ApmcStartDate") or "")[:10]}

    def price_markets(self) -> list[dict]:
        """Markets as named in the price tables (main yards and some sub-yards), with short codes."""
        data = self._xhr(PRICE_PAGE, "/ApmcDetail/GetApmcForArrivalPriceInfo", accept_json=True).json()
        return [{"code": a["ApmcCode"], "name_mr": a["ApmcNameM"]} for a in data]

    def prices(self, commodity_code: str) -> list[PriceRow]:
        resp = self._xhr(PRICE_PAGE, "/ApmcDetail/DataGridBind",
                         {"commodityCode": commodity_code, "apmcCode": "null"})
        return parse_price_table(resp.text)
