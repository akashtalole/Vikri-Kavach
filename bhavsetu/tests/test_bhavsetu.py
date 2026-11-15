import copy
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from bhavsetu import analytics, bulletin, catalog, patti
from bhavsetu.llm import Claude
from bhavsetu.msamb import MsambClient, PriceRow, parse_price_table
from bhavsetu.store import Store
from bhavsetu.web import create_app

FIXTURES = Path(__file__).parent / "fixtures"
ONION = "08035"

# Test APMC master: real names and codes from msamb.com; coordinates are approximate test values.
MASTER = {
    "apmcs": [
        {"full_code": "A1", "code": "035", "name_en": "Chhatrapati Sambhajinagar", "name_mr": "छत्रपती संभाजीनगर",
         "district_en": "Chhatrapati Sambhajinagar", "district_mr": "छत्रपती संभाजीनगर", "lat": 19.88, "lon": 75.34},
        {"full_code": "A2", "code": "159", "name_en": "Daund", "name_mr": "दौंड",
         "district_en": "Pune", "district_mr": "पुणे", "lat": 18.46, "lon": 74.58},
        {"full_code": "A3", "code": "161", "name_en": "Shirur", "name_mr": "शिरुर",
         "district_en": "Pune", "district_mr": "पुणे", "lat": 18.83, "lon": 74.37},
    ],
    "price_markets": [{"code": "035", "name_mr": "छत्रपती संभाजीनगर"}, {"code": "15901", "name_mr": "दौंड-केडगाव"},
                      {"code": "16103", "name_mr": "शिरुर-कांदा मार्केट"}],
}


@pytest.fixture(autouse=True)
def master(tmp_path, monkeypatch):
    path = tmp_path / "master.json"
    path.write_text(json.dumps(MASTER, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("BHAVSETU_APMC_MASTER", str(path))
    catalog.reload_master()
    yield
    catalog.reload_master()


@pytest.fixture
def store():
    s = Store()
    s.upsert_prices(ONION, parse_price_table((FIXTURES / "msamb_onion_datagrid.html").read_text(encoding="utf-8")))
    return s


def row(day, market, arrival, lo, hi, modal, variety=""):
    return PriceRow(day, market, variety, "क्विंटल", arrival, lo, hi, modal)


def test_parse_real_msamb_response():
    rows = parse_price_table((FIXTURES / "msamb_onion_datagrid.html").read_text(encoding="utf-8"))
    assert len(rows) == 11
    first = [r for r in rows if r.price_date == date(2026, 11, 15) and r.market == "छत्रपती संभाजीनगर"][0]
    assert (first.arrival, first.min_price, first.max_price, first.modal_price) == (2130, 2000, 4500, 3250)
    assert first.variety == "" and first.unit == "क्विंटल"
    assert len({r.price_date for r in rows}) >= 3


def test_market_names_map_to_apmcs_including_sub_yards():
    assert catalog.apmc_for_market("दौंड-केडगाव")["district_en"] == "Pune"
    assert catalog.apmc_for_market("शिरुर-कांदा मार्केट")["name_en"] == "Shirur"
    assert catalog.apmc_for_market("छत्रपती संभाजीनगर")["code"] == "035"
    assert catalog.apmc_for_market("unknown market") is None


def test_best_markets_ranks_by_net_after_transport(store):
    origin = (18.83, 74.37)  # at Shirur
    far_away = analytics.best_markets(store, ONION, origin, 20, analytics.Costs(transport_per_qtl_km=1.0))
    names = [o["market"] for o in far_away["options"]]
    assert set(names) == {"छत्रपती संभाजीनगर", "दौंड-केडगाव", "शिरुर-कांदा मार्केट"}
    nets = [o["net_total"] for o in far_away["options"]]
    assert nets == sorted(nets, reverse=True)
    assert far_away["nearest"]["market"] == "शिरुर-कांदा मार्केट"
    for o in far_away["options"]:
        assert o["net_per_qtl"] == round(o["modal"] - o["distance_km"] * 1.0)
    expensive = analytics.best_markets(store, ONION, origin, 20, analytics.Costs(transport_per_qtl_km=50))
    assert expensive["options"][0]["market"] == "शिरुर-कांदा मार्केट"  # transport dominates
    assert analytics.best_markets(store, ONION, origin, 20, max_km=5)["options"][0]["distance_km"] <= 5


def test_arrival_pressure_and_trend():
    s = Store()
    base = date(2026, 11, 1)
    rows = [row(base + timedelta(days=i), "दौंड-केडगाव", 1000, 1500, 3000, 2500) for i in range(5)]
    rows.append(row(base + timedelta(days=5), "दौंड-केडगाव", 2400, 1200, 2800, 2000))
    s.upsert_prices(ONION, rows)
    today = s.day(ONION, base + timedelta(days=5))[0]
    p = analytics.arrival_pressure(s, today)
    assert p["level"] == "glut" and p["ratio"] == 2.4 and p["usual_arrival"] == 1000
    assert analytics.trend(s, today)["change_pct"] == -20.0
    one_day = Store()
    one_day.upsert_prices(ONION, rows[:1])
    assert analytics.arrival_pressure(one_day, one_day.day(ONION, base)[0]) is None


def test_fair_price_check(store):
    d = date(2026, 11, 15)
    low = analytics.fair_price_check(store, ONION, "छत्रपती संभाजीनगर", d, 1800)
    assert low["verdict"] == "below_day_minimum" and low["gap_to_modal_per_qtl"] == 1450
    assert analytics.fair_price_check(store, ONION, "छत्रपती संभाजीनगर", d, 2300)["verdict"] == "bottom_quarter"
    assert analytics.fair_price_check(store, ONION, "छत्रपती संभाजीनगर", d, 3300)["verdict"] == "at_or_above_modal"
    assert not analytics.fair_price_check(store, ONION, "छत्रपती संभाजीनगर", date(2020, 1, 1), 3000)["found"]


SLIP = {"readable": True, "market": "छत्रपती संभाजीनगर", "sale_date": "2026-11-15", "trader_or_agent": "Test Traders",
        "commodity": "कांदा", "lines": [{"description": "कांदा", "quantity_qtl": 10, "rate_per_qtl": 2200, "amount": 22000}],
        "gross_amount": 22000, "deductions": [{"label": "हमाली", "kind": "hamali", "amount": 300},
                                              {"label": "आडत", "kind": "commission", "amount": 1320}],
        "net_paid": 20380, "payment_mode": "cash", "illegible_parts": ""}


def test_patti_checks_arithmetic_rules_and_market_rate(store):
    rules = patti.load_rules()
    rules["deductions"]["commission"].update(charged_to_farmer=False, source="Test rule")
    result = patti.check_slip(copy.deepcopy(SLIP), rules, store, ONION)
    codes = {f["code"] for f in result["findings"]}
    assert "not_allowed_commission" in codes and "low_rate" in codes and "cash" in codes
    assert "net_math" not in codes and result["summary"]["deductions_pct"] == 7.4

    broken = copy.deepcopy(SLIP)
    broken["lines"][0]["amount"] = 23000
    broken["net_paid"] = 21000
    codes = {f["code"] for f in patti.check_slip(broken, patti.load_rules())["findings"]}
    assert {"line_math", "gross_math", "net_math"} <= codes

    clean = copy.deepcopy(SLIP)
    clean.update(deductions=[], net_paid=22000, payment_mode="bank_transfer")
    assert patti.check_slip(clean, patti.load_rules())["findings"][0]["code"] == "no_issue"
    assert patti.check_slip({"readable": False}, rules)["findings"][0]["code"] == "unreadable"
    assert patti.guess_commodity("कांदा") == ONION and patti.guess_commodity("Soybean") == "04017"


class FakeMessages:
    def __init__(self, texts):
        self.texts, self.calls = list(texts), []

    def create(self, **kw):
        self.calls.append(copy.deepcopy(kw))
        t = self.texts.pop(0)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=t)],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def fake(texts):
    msgs = FakeMessages(texts)
    return Claude(client=SimpleNamespace(beta=SimpleNamespace(messages=msgs))), msgs


def test_bulletin_numbers_are_verified(store):
    facts = analytics.district_facts(store, "Pune", [ONION])
    assert facts and facts[0]["markets"] == 2
    good = f"पुण्यात आज कांद्याचा सर्वाधिक भाव {facts[0]['highest_modal']} रुपये ({facts[0]['highest_market']})."
    claude, msgs = fake([good])
    b = bulletin.make_bulletin(claude, store, "Pune", [ONION])
    assert b["method"] == "ai_verified" and b["text"] == good
    assert msgs.calls[0]["output_config"] == {"effort": "low"} and msgs.calls[0]["fallbacks"] == "default"

    devanagari_bad = "कांदा ९९९९ रुपये."
    claude, msgs = fake([devanagari_bad, "कांदा 12345 रुपये."])
    b = bulletin.make_bulletin(claude, store, "Pune", [ONION])
    assert b["method"] == "template_after_failed_check" and "9999" in msgs.calls[1]["messages"][-1]["content"]
    assert str(facts[0]["highest_modal"]) in b["text"]
    assert bulletin.make_bulletin(None, store, "Pune", [ONION])["method"] == "template"


def test_web_pages_and_api(store):
    client = TestClient(create_app(store=store, claude=None))
    page = client.get("/", params={"crop": ONION, "home_apmc": "A3", "qty": 20}).text
    assert "Best net market today" in page and "शिरुर-कांदा मार्केट" in page
    assert "Was I paid a fair price" in client.get("/check").text
    checked = client.get("/check", params={"crop": ONION, "market": "छत्रपती संभाजीनगर", "day": "2026-11-15",
                                           "price": 1800}).text
    assert "Below the lowest auction price" in checked
    fpc = client.get("/fpc", params={"crop": ONION, "home_apmc": "A1", "qty": 300}).text
    assert "Pooled lot" in fpc
    api = client.get("/api/best-markets", params={"crop": ONION, "lat": 18.83, "lon": 74.37, "qty": 5}).json()
    assert api["options"] and api["latest_date"] == "2026-11-15"
    bul = client.post("/bulletin", data={"district": "Pune"}).text
    assert "template" in bul
    assert client.get("/data").status_code == 200


def test_client_needs_session_then_parses(monkeypatch):
    fixture = (FIXTURES / "msamb_onion_datagrid.html").read_text(encoding="utf-8")
    seen = []

    def handler(request: httpx.Request):
        seen.append(request.url.path)
        if request.url.path.endswith("APMCPriceInformation"):
            return httpx.Response(200, text='<select id="drpCommodities" name="drpCommodities"><option value="">x</option>'
                                             '<option value="08035">कांदा</option></select>')
        if request.url.path.endswith("DataGridBind"):
            assert request.headers["X-Requested-With"] == "XMLHttpRequest"
            assert request.url.params["commodityCode"] == ONION
            return httpx.Response(200, text=fixture)
        return httpx.Response(404)

    client = MsambClient(http=httpx.Client(transport=httpx.MockTransport(handler)), pause_seconds=0)
    assert client.commodities() == [("08035", "कांदा")]
    assert len(client.prices(ONION)) == 11
    assert seen[0].endswith("APMCPriceInformation")


def test_variety_filter_compares_like_with_like():
    s = Store()
    d = date(2026, 11, 15)
    s.upsert_prices(ONION, [row(d, "छत्रपती संभाजीनगर", 100, 3000, 5000, 4500, "लाल"),
                            row(d, "दौंड-केडगाव", 100, 1500, 3000, 2600, "उन्हाळी"),
                            row(d, "शिरुर-कांदा मार्केट", 100, 1500, 3000, 2400, "लाल")])
    assert analytics.current_varieties(s, ONION)[0] == "लाल"
    red = analytics.best_markets(s, ONION, (18.83, 74.37), 10, variety="लाल")
    assert {o["market"] for o in red["options"]} == {"छत्रपती संभाजीनगर", "शिरुर-कांदा मार्केट"}
    assert all(o["variety"] == "लाल" for o in red["options"])
