from dataclasses import replace
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import security
from app.config import load
from app.jobs import claim, run_daily, upsert_prices
from app.main import create_app
from app.models import Price, Trader, User

TODAY = date(2026, 11, 14)
H = {"x-requested-with": "vikrikavach"}


def _png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    return buf.getvalue()


PNG = _png()


class Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    settings = replace(load(), database_url=f"sqlite:///{tmp_path}/t.db", upload_dir=str(tmp_path / "up"),
                       otp_mode="dev", static_dir="", scheduler=False)
    app = create_app(settings, today=lambda: TODAY)
    Session = app.state.Session
    with Session() as db:
        db.add(User(role="officer", username="lasalgaon", apmc_code=APMC, name="Secretary",
                    password_hash=security.hash_password("officer-pass-123")))
        db.add(Trader(apmc_code=APMC, licence_no="L-101", name="Good Traders", status="active"))
        db.add(Trader(apmc_code=APMC, licence_no="L-666", name="Suspended Co", status="suspended",
                      status_note="Unpaid dues"))
        upsert_prices(db, "08035", [Row(market=MARKET, variety="Red", price_date=TODAY - timedelta(days=1),
                                        arrival=1000, min_price=1500, max_price=2500, modal_price=2100)])
        db.commit()
    return TestClient(app), Session


from bhavsetu.catalog import apmc_master  # noqa: E402

APMC = apmc_master()["apmcs"][0]["full_code"]
MARKET = "लासलगाव"


def login_farmer(client, phone="9876543210"):
    r = client.post("/api/auth/otp/request", json={"phone": phone}, headers=H)
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    r = client.post("/api/auth/otp/verify", json={"phone": phone, "code": code}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def sale_body(**kw):
    body = {"apmc_code": APMC, "market_name": MARKET, "licence_no": "L-101", "trader_name": "Good Traders",
            "commodity_code": "08035", "variety": "Red", "bags": 40, "own_weight_qtl": 20.0, "slip_weight_qtl": 19.2,
            "rate_per_qtl": 1600, "gross_amount": 30720, "deductions": [{"label": "Hamali", "kind": "hamali", "amount": 200}],
            "net_amount": 30520, "payment_mode": "cheque", "sale_date": (TODAY - timedelta(days=1)).isoformat()}
    body.update(kw)
    return body


def test_health_and_csrf(env):
    client, _ = env
    assert client.get("/api/health").json()["ok"]
    assert client.post("/api/auth/otp/request", json={"phone": "9876543210"}).status_code == 403


def test_otp_login_and_wrong_code(env):
    client, _ = env
    client.post("/api/auth/otp/request", json={"phone": "9876543210"}, headers=H)
    assert client.post("/api/auth/otp/verify", json={"phone": "9876543210", "code": "000000"}, headers=H).status_code == 400
    me = login_farmer(client)
    assert me["role"] == "farmer" and me["phone"] == "+919876543210"
    assert client.get("/api/me").json()["id"] == me["id"]
    assert client.post("/api/auth/otp/request", json={"phone": "12345"}, headers=H).status_code == 400


def test_sale_checks_find_weight_gap_low_rate_and_register(env):
    client, _ = env
    login_farmer(client)
    r = client.post("/api/sales", json=sale_body(), headers=H)
    assert r.status_code == 200, r.text
    s = r.json()
    codes = {f["code"] for f in s["findings"]}
    assert "weight_gap" in codes and "rate_low" in codes
    assert s["risk"] == "high" and s["trader_registered"] and s["reference"].startswith("VK-2026-")
    r = client.post("/api/sales", json=sale_body(licence_no="L-666", rate_per_qtl=1400, gross_amount=26880,
                                                 net_amount=26680), headers=H)
    codes = {f["code"] for f in r.json()["findings"]}
    assert {"trader_suspended", "rate_below_min"} <= codes
    r = client.post("/api/sales", json=sale_body(licence_no="X-9", gross_amount=99999), headers=H)
    codes = {f["code"] for f in r.json()["findings"]}
    assert {"trader_unregistered", "gross_math"} <= codes


def test_payments_overdue_bounce_and_daily_job(env):
    client, Session = env
    login_farmer(client)
    sid = client.post("/api/sales", json=sale_body(), headers=H).json()["id"]
    s = client.post(f"/api/sales/{sid}/payments", headers=H,
                    json={"kind": "cheque_bounced", "amount": 30520, "on_date": TODAY.isoformat()}).json()
    assert s["status"] == "bounced" and any(f["code"] == "cheque_bounced" for f in s["findings"])
    s = client.post(f"/api/sales/{sid}/payments", headers=H,
                    json={"kind": "received", "amount": 30520, "on_date": TODAY.isoformat()}).json()
    assert s["status"] == "paid" and s["outstanding"] == 0
    sid2 = client.post("/api/sales", json=sale_body(sale_date=(TODAY - timedelta(days=1)).isoformat(),
                                                    payment_due=TODAY.isoformat()), headers=H).json()["id"]
    out = run_daily(Session, client=_NoMsamb(), day=TODAY + timedelta(days=2))
    assert out["overdue_marked"] == 1
    assert run_daily(Session, client=_NoMsamb(), day=TODAY + timedelta(days=2)) == {}
    assert client.get(f"/api/sales/{sid2}").json()["status"] == "overdue"
    assert any("overdue" in n["text"] for n in client.get("/api/notifications").json())


class _NoMsamb:
    def prices(self, code):
        return []


def test_evidence_upload_and_reuse(env):
    client, _ = env
    login_farmer(client)
    a = client.post("/api/sales", json=sale_body(), headers=H).json()["id"]
    b = client.post("/api/sales", json=sale_body(), headers=H).json()["id"]
    bad = client.post(f"/api/sales/{a}/evidence", data={"kind": "patti"}, files={"file": ("x.txt", b"hello")}, headers=H)
    assert bad.status_code == 415
    s = client.post(f"/api/sales/{a}/evidence", data={"kind": "patti"}, files={"file": ("p.png", PNG)}, headers=H).json()
    assert len(s["evidence"]) == 1
    assert client.get(f"/api/evidence/{s['evidence'][0]['id']}").content == PNG
    s = client.post(f"/api/sales/{b}/evidence", data={"kind": "patti"}, files={"file": ("p.png", PNG)}, headers=H).json()
    assert any(f["code"] == "evidence_reused" for f in s["findings"])


def test_farmers_cannot_see_each_other(env):
    client, _ = env
    login_farmer(client, "9876543210")
    sid = client.post("/api/sales", json=sale_body(), headers=H).json()["id"]
    other = TestClient(client.app)
    login_farmer(other, "9123456780")
    assert other.get(f"/api/sales/{sid}").status_code == 404
    assert other.get("/api/sales").json() == []
    assert other.get("/api/officer/dashboard").status_code == 403


def test_complaint_flow_and_officer_dashboard(env):
    client, _ = env
    login_farmer(client)
    sid = client.post("/api/sales", json=sale_body(), headers=H).json()["id"]
    client.post("/api/sales", json=sale_body(), headers=H)
    assert client.post(f"/api/sales/{sid}/complaint", json={"categories": []}, headers=H).status_code == 400
    c = client.post(f"/api/sales/{sid}/complaint", json={"categories": ["weight", "rate"],
                                                         "description": "Scale showed less"}, headers=H).json()
    assert c["reference"].startswith("VKC-")
    assert client.post(f"/api/sales/{sid}/complaint", json={"categories": ["weight"]}, headers=H).status_code == 409
    pack = client.get(f"/api/complaints/{c['id']}/pack")
    assert pack.status_code == 200 and "Scale showed less" in pack.text and "weighbridge" in pack.text

    staff = TestClient(client.app)
    assert staff.post("/api/auth/staff/login", json={"username": "lasalgaon", "password": "wrong-password"},
                      headers=H).status_code == 401
    assert staff.post("/api/auth/staff/login", json={"username": "lasalgaon", "password": "officer-pass-123"},
                      headers=H).status_code == 200
    d = staff.get("/api/officer/dashboard").json()
    assert d["totals"]["open_complaints"] == 1
    t = d["traders"][0]
    assert t["licence_no"] == "L-101" and t["weight_gap_sales"] == 2 and t["flag"]
    assert any("New complaint" in n["text"] for n in staff.get("/api/notifications").json())
    detail = staff.get(f"/api/officer/complaints/{c['id']}").json()
    assert detail["sale"]["reference"]
    r = staff.patch(f"/api/officer/complaints/{c['id']}", json={"status": "resolved", "officer_note": "Trader paid"},
                    headers=H)
    assert r.json()["status"] == "resolved"
    assert any("Trader paid" in n["text"] for n in client.get("/api/notifications").json())


def test_trader_register_links_earlier_sales(env):
    client, _ = env
    login_farmer(client)
    sid = client.post("/api/sales", json=sale_body(licence_no="L-202"), headers=H).json()["id"]
    assert not client.get(f"/api/sales/{sid}").json()["trader_registered"]
    staff = TestClient(client.app)
    staff.post("/api/auth/staff/login", json={"username": "lasalgaon", "password": "officer-pass-123"}, headers=H)
    r = staff.post("/api/officer/traders", json={"licence_no": "L-202", "name": "New Trader", "status": "cancelled",
                                                 "status_note": "Licence cancelled"}, headers=H)
    assert r.status_code == 200
    s = client.get(f"/api/sales/{sid}").json()
    assert s["trader_registered"] and any(f["code"] == "trader_cancelled" for f in s["findings"])
    found = client.get("/api/traders/lookup", params={"apmc_code": APMC, "licence_no": "l-202"}).json()
    assert found[0]["status"] == "cancelled"


def test_slip_read_uses_ai_when_configured(tmp_path, monkeypatch):
    class FakeClaude:
        def json(self, messages, schema, effort=None):
            return {"readable": True, "net_paid": 1000}

    settings = replace(load(), database_url=f"sqlite:///{tmp_path}/t.db", upload_dir=str(tmp_path / "up"))
    client = TestClient(create_app(settings, claude=FakeClaude(), today=lambda: TODAY))
    login_farmer(client)
    r = client.post("/api/slips/read", files={"file": ("p.png", PNG)}, headers=H)
    assert r.status_code == 200 and r.json()["net_paid"] == 1000


def test_job_claim_is_once_per_day(env):
    _, Session = env
    with Session() as db:
        assert claim(db, "x", TODAY) and not claim(db, "x", TODAY)
        assert db.query(Price).count() == 1


def test_price_upsert_dedupes_same_key(env):
    _, Session = env
    d = TODAY - timedelta(days=2)
    rows = [Row(market="X", variety="V", price_date=d, arrival=1, min_price=1, max_price=2, modal_price=1),
            Row(market="X", variety="V", price_date=d, arrival=2, min_price=3, max_price=4, modal_price=3)]
    with Session() as db:
        assert upsert_prices(db, "08035", rows) == 1
        assert db.query(Price).filter_by(market="X").one().modal_price == 3


def test_stale_job_claim_can_be_taken_over(env):
    from datetime import datetime, timezone

    from app.jobs import STALE_AFTER, finish
    from app.models import JobRun

    _, Session = env
    with Session() as db:
        assert claim(db, "prices", TODAY)
        assert not claim(db, "prices", TODAY)  # running elsewhere
        run = db.query(JobRun).filter_by(job="prices").one()
        run.started_at = datetime.now(timezone.utc) - STALE_AFTER * 2  # that container died
        db.commit()
        assert claim(db, "prices", TODAY)
        finish(db, "prices", TODAY, {"08035": 3})
        run = db.query(JobRun).filter_by(job="prices").one()
        run.started_at = datetime.now(timezone.utc) - STALE_AFTER * 2
        db.commit()
        assert not claim(db, "prices", TODAY)  # finished runs are never repeated


def test_seed_demo_is_idempotent(tmp_path, monkeypatch):
    from app.cli import main

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/s.db")
    monkeypatch.setenv("STAFF_PASSWORD", "demo-officer-pass")
    assert main(["seed-demo", "--apmc-code", APMC]) == 0
    assert main(["seed-demo", "--apmc-code", APMC]) == 0


def test_create_staff_with_hash_and_reset(tmp_path, monkeypatch, capsys):
    from app.cli import main

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/c.db")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("first-password-1\n"))
    assert main(["hash-password", "--stdin"]) == 0
    h = capsys.readouterr().out.strip()
    assert main(["create-staff", "--username", "Sec1", "--apmc-code", APMC, "--password-hash", h]) == 0
    assert main(["create-staff", "--username", "sec1", "--apmc-code", APMC, "--password-hash", "nope"]) == 1
    monkeypatch.setenv("STAFF_PASSWORD", "second-password-2")
    assert main(["create-staff", "--username", "sec1", "--apmc-code", APMC]) == 0  # resets, no duplicate
    settings = replace(load(), database_url=f"sqlite:///{tmp_path}/c.db")
    client = TestClient(create_app(settings, today=lambda: TODAY))
    assert client.post("/api/auth/staff/login", json={"username": "sec1", "password": "second-password-2"},
                       headers=H).status_code == 200


def test_import_traders_csv(tmp_path, monkeypatch, capsys):
    from app.cli import main

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/i.db")
    csv_file = tmp_path / "reg.csv"
    csv_file.write_text("licence_no,name,firm,status\nA-1,Alpha,Alpha Co,active\nB-2,Beta,,Suspended\nC-3,Gamma,,unknown\n")
    assert main(["import-traders", "--apmc-code", APMC, str(csv_file)]) == 0
    assert '"imported": 2' in capsys.readouterr().out
