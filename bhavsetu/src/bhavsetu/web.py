"""Web app: farmer tools (best market, fair-price check, patti audit), FPC console, district bulletin, JSON API."""

from __future__ import annotations

import os
import secrets
from datetime import date
from html import escape

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import analytics, bulletin, patti
from .catalog import MAIN_CROPS, apmc_master, crop_label
from .llm import Claude, LLMError
from .store import Store

security = HTTPBasic(auto_error=False)

CSS = """<style>
:root{--ink:#1f2937;--muted:#6b7280;--navy:#1b2a5c;--line:#e5e7eb;--ok:#047857;--warn:#b45309;--bad:#b91c1c;--bg:#fff}
*{box-sizing:border-box}body{margin:0 auto;max-width:1040px;padding:16px;font-family:system-ui,"Noto Sans Devanagari",sans-serif;
color:var(--ink);background:var(--bg);line-height:1.5}h1{color:var(--navy);font-size:26px;margin:.4em 0}h2{color:var(--navy);font-size:18px}
nav{display:flex;gap:14px;flex-wrap:wrap;font-size:14px}.muted{color:var(--muted)}.box{border:1px solid var(--line);border-radius:10px;
padding:14px;margin:12px 0}form.f{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;align-items:end}
form.f label{display:grid;gap:4px;font-size:14px;font-weight:600}input,select{font:inherit;padding:9px;border:1px solid #c5ccd1;
border-radius:8px;width:100%}button{font:inherit;font-weight:600;padding:10px 16px;border:0;border-radius:8px;background:var(--navy);
color:#fff;cursor:pointer}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:6px 8px;border-bottom:1px solid var(--line);
text-align:left;vertical-align:top}td.n{text-align:right;font-variant-numeric:tabular-nums}.wrap{overflow-x:auto}.tag{display:inline-block;
padding:1px 8px;border-radius:999px;font-size:12px;background:#eef2ff}.glut{background:#fee2e2}.low{background:#d1fae5}.high{color:var(--bad)}
.medium{color:var(--warn)}.ok{color:var(--ok)}.best{background:#f0fdf4}</style>"""

NAV = ('<nav><a href="/">Best market</a><a href="/check">Fair-price check</a><a href="/patti">Sale-slip audit</a>'
       '<a href="/fpc">FPC console</a><a href="/bulletin">District bulletin</a><a href="/data">Data</a></nav>')


def page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="mr"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{escape(title)}</title>{CSS}</head><body>{NAV}{body}'
            f'<p class="muted" style="margin-top:32px;font-size:13px">Prices: Maharashtra State Agricultural Marketing '
            f'Board (msamb.com), refreshed daily. APMC locations: OpenStreetMap contributors.</p></body></html>')


def crop_options(selected: str | None = None) -> str:
    return "".join(f"<option value='{c}'{' selected' if c == selected else ''}>{escape(crop_label(c))}</option>"
                   for c in MAIN_CROPS)


def apmc_options(selected: str | None = None) -> str:
    groups: dict[str, list[dict]] = {}
    for a in apmc_master()["apmcs"]:
        if a.get("lat") is not None:
            groups.setdefault(a["district_en"], []).append(a)
    out = []
    for district in sorted(groups):
        opts = "".join(f"<option value='{escape(a['full_code'])}'{' selected' if a['full_code'] == selected else ''}>"
                       f"{escape(a['name_mr'])} ({escape(a['name_en'])})</option>"
                       for a in sorted(groups[district], key=lambda x: x["name_en"]))
        out.append(f"<optgroup label='{escape(district)}'>{opts}</optgroup>")
    return "".join(out)


def origin_from(home: str | None, lat: float | None, lon: float | None) -> tuple[float, float] | None:
    if lat is not None and lon is not None:
        return (lat, lon)
    for a in apmc_master()["apmcs"]:
        if a["full_code"] == home and a.get("lat") is not None:
            return (a["lat"], a["lon"])
    return None


def pressure_tag(p: dict | None) -> str:
    if not p:
        return "<span class='muted'>-</span>"
    label = {"glut": "heavy arrivals", "low": "light arrivals", "normal": "normal"}[p["level"]]
    return f"<span class='tag {p['level']}' title='{p['ratio']}x usual ({p['usual_arrival']})'>{label} x{p['ratio']}</span>"


def market_table(result: dict) -> str:
    if not result["options"]:
        return "<p class='box'>No market with a current price and a known location within range.</p>"
    rows = []
    for i, o in enumerate(result["options"]):
        t = o["trend"]
        trend_txt = "-" if not t else f"{t['change_pct']:+g}%"
        rows.append(
            f"<tr class='{'best' if i == 0 else ''}'><td>{i + 1}</td><td>{escape(o['market'])}"
            f"{(' <span class=muted>' + escape(o['variety']) + '</span>') if o['variety'] else ''}"
            f"<br><span class='muted'>{escape(o['district'] or '')}, {o['price_date']}</span></td>"
            f"<td class='n'>{o['modal']:,.0f}<br><span class='muted'>{o['min']:,.0f}-{o['max']:,.0f}</span></td>"
            f"<td class='n'>{o['distance_km']}</td><td class='n'>{o['cost_per_qtl']:,}</td><td class='n'><b>{o['net_per_qtl']:,}</b></td>"
            f"<td class='n'><b>{o['net_total']:,}</b><br><span class='{'ok' if o['gain_vs_nearest'] > 0 else 'muted'}'>"
            f"{o['gain_vs_nearest']:+,} vs nearest</span></td><td>{pressure_tag(o['pressure'])}</td><td class='n'>{trend_txt}</td></tr>")
    return ("<div class='wrap'><table><thead><tr><th>#</th><th>Market</th><th>Modal (min-max) Rs/qtl</th><th>km</th>"
            "<th>Cost Rs/qtl</th><th>Net Rs/qtl</th><th>Net total Rs</th><th>Arrivals today</th><th>vs earlier days</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
            f"<p class='muted'>{escape(result['note'])} Markets considered: {result['markets_considered']}.</p>")


def create_app(store: Store | None = None, claude: Claude | None = None) -> FastAPI:
    store = store or Store(os.environ.get("BHAVSETU_DB", "var/bhavsetu.db"))
    password = os.environ.get("BHAVSETU_PASSWORD", "")
    state = {"claude": claude}
    app = FastAPI(title="BhavSetu")

    def ai_user(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
        """AI features cost money per call; protect them when a password is set."""
        if password and (credentials is None or not secrets.compare_digest(credentials.password.encode(),
                                                                            password.encode())):
            raise HTTPException(401, "Login required", headers={"WWW-Authenticate": 'Basic realm="BhavSetu"'})

    def get_claude() -> Claude:
        if state["claude"] is None:
            if not any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")):
                raise HTTPException(503, "Claude is not configured on this server (set ANTHROPIC_API_KEY)")
            try:
                state["claude"] = Claude()
            except Exception as exc:
                raise HTTPException(503, f"Claude is not configured: {type(exc).__name__}") from exc
        return state["claude"]

    def costs(transport: float, fixed: float, pct: float) -> analytics.Costs:
        return analytics.Costs(max(transport, 0), max(fixed, 0), min(max(pct, 0), 20))

    @app.get("/health")
    def health():
        return {"ok": True, "apmcs_with_location": sum(1 for a in apmc_master()["apmcs"] if a.get("lat")),
                "crops_with_data": len(store.commodities_with_data())}

    @app.get("/", response_class=HTMLResponse)
    def home(crop: str = "08035", home_apmc: str | None = None, lat: float | None = None, lon: float | None = None,
             qty: float = 20, transport: float = 1.0, fixed: float = 0.0, pct: float = 0.0, max_km: float = 200,
             variety: str = "*"):
        origin = origin_from(home_apmc, lat, lon)
        varieties = analytics.current_varieties(store, crop)
        variety_opts = "<option value='*'>All varieties (compare with care)</option>" + "".join(
            f"<option value='{escape(v)}'{' selected' if v == variety else ''}>{escape(v or 'Not stated')}</option>"
            for v in varieties)
        result_html = ""
        if origin:
            r = analytics.best_markets(store, crop, origin, qty, costs(transport, fixed, pct), max_km=max_km,
                                       variety=None if variety == "*" else variety)
            near = r["nearest"]
            head = ""
            if r["options"] and near:
                top = r["options"][0]
                head = (f"<p class='box best'>Best net market today: <b>{escape(top['market'])}</b>, about "
                        f"<b>Rs {top['net_total']:,}</b> for {qty:g} quintals after costs: Rs {top['gain_vs_nearest']:,} more than "
                        f"the nearest market ({escape(near['market'])}, {near['distance_km']} km).</p>")
            result_html = f"<h2>{escape(crop_label(crop))}: prices of {r['latest_date'] or '-'}</h2>{head}{market_table(r)}"
        return page("BhavSetu - best market", f"""<h1>Where will I get the most for my crop today?</h1>
<p class="muted">Compares today's MSAMB prices at every market within reach and subtracts transport and charges.</p>
<form class="f" method="get"><label>Crop<select name="crop">{crop_options(crop)}</select></label>
<label>From (your nearest market)<select name="home_apmc">{apmc_options(home_apmc)}</select></label>
<label>Variety<select name="variety">{variety_opts}</select></label>
<label>Quantity (quintals)<input name="qty" type="number" step="0.5" min="0.5" value="{qty:g}"></label>
<label>Transport Rs per quintal per km<input name="transport" type="number" step="0.1" min="0" value="{transport:g}"></label>
<label>Other charges Rs per quintal<input name="fixed" type="number" step="1" min="0" value="{fixed:g}"></label>
<label>Charges as % of value<input name="pct" type="number" step="0.1" min="0" max="20" value="{pct:g}"></label>
<label>Max distance km<input name="max_km" type="number" step="10" min="10" max="600" value="{max_km:g}"></label>
<input type="hidden" name="lat" id="lat"><input type="hidden" name="lon" id="lon">
<button>Compare markets</button><button type="button" onclick="navigator.geolocation.getCurrentPosition(p=>{{lat.value=p.coords.latitude;
lon.value=p.coords.longitude;this.form.submit()}},e=>alert(e.message))">Use my location</button></form>{result_html}""")

    @app.get("/check", response_class=HTMLResponse)
    def check(crop: str = "08035", market: str = "", day: str = "", price: float | None = None):
        out = ""
        if market and day and price:
            try:
                d = date.fromisoformat(day)
            except ValueError:
                raise HTTPException(400, "date must be YYYY-MM-DD")
            r = analytics.fair_price_check(store, crop, market.strip(), d, price)
            if not r["found"]:
                out = f"<p class='box'>{escape(r['note'])}</p>"
            else:
                verdicts = {"below_day_minimum": ("high", "Below the lowest auction price recorded that day"),
                            "bottom_quarter": ("medium", "In the bottom quarter of that day's range"),
                            "below_modal": ("muted", "Below the modal (most common) price"),
                            "at_or_above_modal": ("ok", "At or above the modal price")}
                css, text = verdicts[r["verdict"]]
                out = (f"<div class='box'><p class='{css}'><b>{text}.</b></p><p>{escape(r['market'])}, {r['date']}: "
                       f"range Rs {r['min']:,.0f}-{r['max']:,.0f}, modal Rs {r['modal']:,.0f}, arrivals {r['arrival'] or '-'}. "
                       f"You received Rs {price:,.0f} (Rs {r['gap_to_modal_per_qtl']:,} below modal per quintal)."
                       f"</p><p>District median modal: {r['district_median_modal'] or '-'}; state median: {r['state_median_modal']}.</p>"
                       f"<p class='muted'>{escape(r['note'])}</p></div>")
        markets = sorted({x["market"] for x in store.all("SELECT DISTINCT market FROM prices WHERE commodity_code = ?", (crop,))})
        options = "".join(f"<option value='{escape(m)}'>" for m in markets)
        return page("BhavSetu - fair price", f"""<h1>Was I paid a fair price?</h1>
<p class="muted">Compares the rate on your sale with that day's auction range at the same market.</p>
<form class="f" method="get"><label>Crop<select name="crop">{crop_options(crop)}</select></label>
<label>Market<input name="market" list="mk" value="{escape(market)}" required><datalist id="mk">{options}</datalist></label>
<label>Sale date<input name="day" type="date" value="{escape(day)}" required></label>
<label>Rate received Rs/quintal<input name="price" type="number" min="1" value="{'' if price is None else f'{price:g}'}" required></label>
<button>Check</button></form>{out}""")

    @app.get("/patti", response_class=HTMLResponse)
    def patti_form():
        return page("BhavSetu - sale slip", f"""<h1>Check my sale slip (patti)</h1>
<p class="muted">Upload a clear photo of the slip. Claude reads it; the arithmetic, the deductions against configured
rules, and the rate against that day's market range are checked by code. Nothing is stored.</p>
<form class="f" method="post" action="/patti" enctype="multipart/form-data"><label>Photo or PDF of the slip
<input type="file" name="slip" accept="image/*,application/pdf" required></label><label>Crop (if not clear on the slip)
<select name="crop"><option value="">From the slip</option>{crop_options()}</select></label><button>Check slip</button></form>""")

    @app.post("/patti", response_class=HTMLResponse)
    async def patti_check(slip: UploadFile = File(...), crop: str = Form(""), _: None = Depends(ai_user)):
        data = await slip.read()
        if not data or len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "upload a photo up to 10 MB")
        try:
            read = patti.read_slip(get_claude(), data)
        except (LLMError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        code = crop or patti.guess_commodity(read.get("commodity", ""))
        result = patti.check_slip(read, store=store, commodity_code=code)
        items = "".join(f"<li class='{f['severity']}'>{escape(f['message'])}</li>" for f in result["findings"])
        s = result["summary"] or {}
        deds = "".join(f"<tr><td>{escape(d['label'])}</td><td>{escape(d['kind'])}</td><td class='n'>{d['amount']:,.2f}</td></tr>"
                       for d in read["deductions"])
        return page("BhavSetu - slip result", f"""<h1>Sale slip check</h1><ul class="box">{items}</ul>
<p>{escape(read['market'])}, {escape(read['sale_date'])}, {escape(read['commodity'])}. Quantity {s.get('quantity_qtl', '-')} qtl,
average rate Rs {s.get('average_rate', '-')}, gross Rs {s.get('gross', '-')}, deductions Rs {s.get('deductions', '-')}
({s.get('deductions_pct', '-')}%), net paid Rs {s.get('net_paid', '-')}, payment: {escape(read['payment_mode'])}.</p>
<table><thead><tr><th>Deduction</th><th>Type</th><th>Rs</th></tr></thead><tbody>{deds}</tbody></table>
<p class="muted">Not legible: {escape(read['illegible_parts'] or 'nothing noted')}. Check the transcription against your slip.</p>""")

    @app.get("/fpc", response_class=HTMLResponse)
    def fpc(crop: str = "04017", home_apmc: str | None = None, qty: float = 200, transport: float = 0.6,
            fixed: float = 0.0, pct: float = 0.0, max_km: float = 400):
        origin = origin_from(home_apmc, None, None)
        out = ""
        if origin:
            r = analytics.fpc_opportunities(store, crop, origin, qty, costs(transport, fixed, pct), max_km=max_km)
            hot = "".join(f"<li><b>{escape(h['market'])}</b> ({escape(h['district'] or '')}): modal Rs {h['modal']:,.0f}, "
                          f"{h['z_score']:+g} standard deviations above markets in range, arrivals "
                          f"{'normal' if not h['pressure'] else h['pressure']['level']}; net Rs {h['net_per_qtl']:,}/qtl.</li>"
                          for h in r["high_price_markets"]) or "<li>No market stands out today.</li>"
            out = f"<h2>Pooled lot: {qty:g} quintals of {escape(crop_label(crop))}</h2>{market_table(r)}" \
                  f"<h2>Markets with unusually high prices today</h2><ul>{hot}</ul>"
        return page("BhavSetu - FPC console", f"""<h1>FPC console: where to send a pooled lot</h1>
<p class="muted">For Farmer Producer Companies aggregating members' produce. Bulk transport is cheaper per quintal, so
markets further away can pay more net. Set your own truck cost per quintal per km.</p>
<form class="f" method="get"><label>Crop<select name="crop">{crop_options(crop)}</select></label>
<label>FPC location (nearest market)<select name="home_apmc">{apmc_options(home_apmc)}</select></label>
<label>Pooled quantity (quintals)<input name="qty" type="number" min="1" value="{qty:g}"></label>
<label>Truck cost Rs per quintal per km<input name="transport" type="number" step="0.05" min="0" value="{transport:g}"></label>
<label>Other charges Rs per quintal<input name="fixed" type="number" min="0" value="{fixed:g}"></label>
<label>Max distance km<input name="max_km" type="number" min="10" max="800" value="{max_km:g}"></label>
<button>Find markets</button></form>{out}""")

    @app.get("/bulletin", response_class=HTMLResponse)
    def bulletin_form():
        districts = sorted({a["district_en"] for a in apmc_master()["apmcs"]})
        opts = "".join(f"<option>{escape(d)}</option>" for d in districts)
        return page("BhavSetu - bulletin", f"""<h1>District market bulletin</h1>
<p class="muted">A short Marathi bulletin for WhatsApp groups. Claude writes it from computed facts; every number is
checked against the data, and a plain template is used if the check fails.</p>
<form class="f" method="post" action="/bulletin"><label>District<select name="district">{opts}</select></label>
<button>Write bulletin</button></form>""")

    @app.post("/bulletin", response_class=HTMLResponse)
    def bulletin_make(district: str = Form(...), _: None = Depends(ai_user)):
        try:
            claude_client = get_claude()
        except HTTPException:
            claude_client = None
        b = bulletin.make_bulletin(claude_client, store, district)
        method = {"ai_verified": "AI-written, all numbers verified against the data",
                  "template": "template (AI not used)",
                  "template_ai_unavailable": "template (AI call failed)",
                  "template_after_failed_check": "template (AI draft failed the number check)"}[b["method"]]
        return page("BhavSetu - bulletin", f"""<h1>{escape(district)} bulletin</h1>
<div class="box" style="white-space:pre-wrap">{escape(b['text'])}</div><p class="muted">Method: {method}.</p>""")

    @app.get("/data", response_class=HTMLResponse)
    def data_status():
        rows = "".join(f"<tr><td>{escape(crop_label(c))}</td><td>{store.latest_date(c)}</td></tr>"
                       for c in sorted(store.commodities_with_data()))
        located = sum(1 for a in apmc_master()["apmcs"] if a.get("lat"))
        return page("BhavSetu - data", f"""<h1>Data</h1><p>APMCs with a location: {located} of {len(apmc_master()['apmcs'])}.</p>
<table><thead><tr><th>Crop</th><th>Latest prices</th></tr></thead><tbody>{rows or '<tr><td colspan=2>No prices yet: run bhavsetu ingest.</td></tr>'}</tbody></table>""")

    # -- JSON API (for WhatsApp bots, FPC software, dashboards) ------------
    @app.get("/api/best-markets")
    def api_best(crop: str, lat: float, lon: float, qty: float = 10, transport: float = 1.0, fixed: float = 0.0,
                 pct: float = 0.0, max_km: float = Query(200, le=800)):
        return analytics.best_markets(store, crop, (lat, lon), qty, costs(transport, fixed, pct), max_km=max_km)

    @app.get("/api/fair-price")
    def api_fair(crop: str, market: str, day: date, price: float):
        return analytics.fair_price_check(store, crop, market, day, price)

    return app
