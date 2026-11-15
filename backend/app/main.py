"""Vikri Kavach API and web app."""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Literal

from bhavsetu.catalog import MAIN_CROPS, apmc_master, crop_label
from bhavsetu.patti import read_slip
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import checks, security
from .config import Settings, load
from .jobs import Scheduler, today_ist
from .models import (Audit, Complaint, Evidence, Notification, OtpCode, PaymentEvent, Sale, Trader, User, make_engine,
                     make_sessionmaker, utcnow)
from .services import MAX_UPLOAD, SmsSender, Storage, make_claude, sniff_type

log = logging.getLogger("vikrikavach")
COOKIE = "vk_session"
CSRF_HEADER = "x-requested-with"
DEDUCTION_KINDS = Literal["commission", "hamali", "weighing", "market_fee", "transport", "advance_recovery", "other"]
COMPLAINT_CATEGORIES = {"weight", "rate", "deductions", "payment_delay", "cheque_bounced", "unlicensed_trader",
                        "quality_downgrade", "other"}


# -- request bodies ---------------------------------------------------------
class OtpRequest(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    code: str = Field(min_length=6, max_length=6)


class StaffLogin(BaseModel):
    username: str
    password: str


class ProfileUpdate(BaseModel):
    name: str | None = Field(None, max_length=120)
    language: Literal["mr", "hi", "en"] | None = None
    village: str | None = Field(None, max_length=120)
    district: str | None = Field(None, max_length=64)


class Deduction(BaseModel):
    label: str = Field(max_length=60)
    kind: DEDUCTION_KINDS = "other"
    amount: float = Field(ge=0, le=10_000_000)


class SaleIn(BaseModel):
    apmc_code: str
    market_name: str = Field(min_length=1, max_length=120)
    licence_no: str = Field("", max_length=64)
    trader_name: str = Field("", max_length=160)
    commodity_code: str
    variety: str = Field("", max_length=64)
    bags: int | None = Field(None, ge=0, le=100000)
    own_weight_qtl: float | None = Field(None, gt=0, le=100000)
    slip_weight_qtl: float = Field(gt=0, le=100000)
    rate_per_qtl: float = Field(gt=0, le=1_000_000)
    gross_amount: float = Field(ge=0)
    deductions: list[Deduction] = []
    net_amount: float = Field(ge=0)
    payment_mode: Literal["cash", "cheque", "bank_transfer", "upi", "not_stated"] = "not_stated"
    sale_date: date
    payment_due: date | None = None


class PaymentIn(BaseModel):
    kind: Literal["received", "cheque_bounced", "promised"]
    amount: float = Field(0, ge=0, le=10_000_000)
    on_date: date
    note: str = Field("", max_length=500)


class ComplaintIn(BaseModel):
    categories: list[str]
    description: str = Field("", max_length=2000)


class ComplaintUpdate(BaseModel):
    status: Literal["under_review", "resolved", "rejected"]
    officer_note: str = Field("", max_length=2000)


class TraderIn(BaseModel):
    licence_no: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    firm: str = Field("", max_length=160)
    status: Literal["active", "suspended", "cancelled"] = "active"
    status_note: str = Field("", max_length=500)


# -- helpers ----------------------------------------------------------------
def apmc_by_code() -> dict[str, dict]:
    return {a["full_code"]: a for a in apmc_master()["apmcs"]}


def sale_dict(s: Sale, findings: list[dict] | None = None) -> dict:
    out = {
        "id": s.id, "reference": s.reference, "apmc_code": s.apmc_code,
        "apmc_name": apmc_by_code().get(s.apmc_code, {}).get("name_en", s.apmc_code),
        "market_name": s.market_name, "trader_name": s.trader.name if s.trader else s.trader_name,
        "trader_registered": s.trader is not None, "trader_status": s.trader.status if s.trader else None,
        "licence_no": s.licence_no, "commodity_code": s.commodity_code, "crop": crop_label(s.commodity_code),
        "variety": s.variety, "bags": s.bags, "own_weight_qtl": s.own_weight_qtl, "slip_weight_qtl": s.slip_weight_qtl,
        "rate_per_qtl": s.rate_per_qtl, "gross_amount": s.gross_amount, "deductions": s.deductions,
        "net_amount": s.net_amount, "payment_mode": s.payment_mode, "sale_date": s.sale_date.isoformat(),
        "payment_due": s.payment_due.isoformat(), "amount_paid": s.amount_paid,
        "outstanding": round(s.net_amount - s.amount_paid, 2), "status": s.status,
        "evidence": [{"id": e.id, "kind": e.kind, "content_type": e.content_type, "uploaded_at": e.uploaded_at.isoformat()}
                     for e in s.evidence],
        "payments": [{"kind": p.kind, "amount": p.amount, "on_date": p.on_date.isoformat(), "note": p.note}
                     for p in s.payments],
    }
    if findings is not None:
        out["findings"] = findings
        out["risk"] = checks.risk_level(findings)
    return out


def recompute_status(s: Sale, today: date) -> None:
    if any(p.kind == "cheque_bounced" for p in s.payments) and s.amount_paid < s.net_amount:
        s.status = "bounced"
    elif s.amount_paid >= s.net_amount - 0.5:
        s.status = "paid"
    elif today > s.payment_due:
        s.status = "overdue"
    elif s.amount_paid > 0:
        s.status = "partly_paid"
    else:
        s.status = "awaiting_payment"


def create_app(settings: Settings | None = None, claude=None, storage: Storage | None = None,
               sms: SmsSender | None = None, today=today_ist) -> FastAPI:
    settings = settings or load()
    engine = make_engine(settings.database_url)
    Session = make_sessionmaker(engine)
    storage = storage or Storage(settings)
    sms = sms or SmsSender(settings)
    state = {"claude": claude if claude is not None else make_claude(settings)}
    scheduler = Scheduler(Session)

    @asynccontextmanager
    async def lifespan(_app):
        if settings.scheduler:
            scheduler.start()
        yield
        scheduler.stop()

    app = FastAPI(title="Vikri Kavach", version="0.1.0", lifespan=lifespan,
                  docs_url=None if settings.is_production else "/api/docs", openapi_url="/api/openapi.json")
    app.state.Session = Session

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Cookie sessions + a required custom header on writes blocks cross-site form posts (CSRF).
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS") \
                and request.headers.get(CSRF_HEADER) != "vikrikavach":
            return JSONResponse({"detail": "missing request header"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    def db():
        with Session() as session:
            yield session

    def current_user(request: Request, session: Session = Depends(db)) -> User:
        claims = security.read_token(request.cookies.get(COOKIE, ""), settings.jwt_secret)
        user = session.get(User, int(claims["sub"])) if claims else None
        if not user or not user.active:
            raise HTTPException(401, "Please log in")
        return user

    def farmer(user: User = Depends(current_user)) -> User:
        if user.role != "farmer":
            raise HTTPException(403, "Farmer account required")
        return user

    def officer(user: User = Depends(current_user)) -> User:
        if user.role not in ("officer", "admin"):
            raise HTTPException(403, "APMC staff account required")
        return user

    def in_scope(user: User, apmc_code: str) -> bool:
        return user.role == "admin" or user.apmc_code == apmc_code

    def audit(session: Session, actor: User | str, action: str, detail: str = "") -> None:
        who = actor if isinstance(actor, str) else f"{actor.role}:{actor.id}"
        session.add(Audit(actor=who, action=action, detail=detail[:2000]))

    def set_session(response: Response, user: User) -> None:
        response.set_cookie(COOKIE, security.make_token(user.id, user.role, settings.jwt_secret), httponly=True,
                            secure=settings.cookie_secure, samesite="lax", max_age=security.SESSION_HOURS * 3600)

    def load_sale(session: Session, sale_id: int) -> Sale:
        s = session.scalar(select(Sale).where(Sale.id == sale_id).options(
            selectinload(Sale.evidence), selectinload(Sale.payments), selectinload(Sale.trader))
            .execution_options(populate_existing=True))
        if not s:
            raise HTTPException(404)
        return s

    def own_sale(session: Session, sale_id: int, user: User) -> Sale:
        s = load_sale(session, sale_id)
        if s.farmer_id != user.id and not (user.role in ("officer", "admin") and in_scope(user, s.apmc_code)):
            raise HTTPException(404)
        return s

    def me_dict(u: User) -> dict:
        return {"id": u.id, "role": u.role, "name": u.name, "phone": u.phone, "username": u.username,
                "language": u.language, "village": u.village, "district": u.district, "apmc_code": u.apmc_code,
                "apmc_name": apmc_by_code().get(u.apmc_code or "", {}).get("name_en")}

    # -- health and reference data -----------------------------------------
    @app.get("/api/health")
    def health(session: Session = Depends(db)):
        session.execute(select(1))
        return {"ok": True, "ai": state["claude"] is not None, "storage": "s3" if settings.s3_bucket else "local"}

    @app.get("/api/reference")
    def reference():
        return {
            "crops": [{"code": c, "en": en, "mr": mr} for c, (en, mr) in MAIN_CROPS.items()],
            "apmcs": [{"code": a["full_code"], "name_en": a["name_en"], "name_mr": a["name_mr"],
                       "district": a["district_en"]} for a in apmc_master()["apmcs"]],
            "price_markets": [m["name_mr"] for m in apmc_master().get("price_markets", [])],
            "complaint_categories": sorted(COMPLAINT_CATEGORIES),
            "ai_slip_reading": state["claude"] is not None,
        }

    @app.get("/api/traders/lookup")
    def trader_lookup(apmc_code: str, licence_no: str = "", q: str = "", _: User = Depends(current_user),
                      session: Session = Depends(db)):
        stmt = select(Trader).where(Trader.apmc_code == apmc_code)
        if licence_no:
            stmt = stmt.where(func.lower(Trader.licence_no) == licence_no.strip().lower())
        elif q:
            stmt = stmt.where(func.lower(Trader.name).contains(q.strip().lower()))
        else:
            raise HTTPException(400, "give a licence number or a name")
        return [{"id": t.id, "licence_no": t.licence_no, "name": t.name, "firm": t.firm, "status": t.status,
                 "status_note": t.status_note} for t in session.scalars(stmt.limit(10))]

    @app.get("/api/prices/day")
    def price_day(crop: str, market: str, day: date, _: User = Depends(current_user), session: Session = Depends(db)):
        p = checks.day_price(session, crop, market, day)
        return None if not p else {"market": p.market, "variety": p.variety, "date": p.price_date.isoformat(),
                                   "min": p.min_price, "max": p.max_price, "modal": p.modal_price, "arrival": p.arrival}

    # -- authentication ----------------------------------------------------
    @app.post("/api/auth/otp/request")
    def otp_request(body: OtpRequest, session: Session = Depends(db)):
        try:
            phone = security.normalise_phone(body.phone)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        recent = session.scalar(select(func.count()).select_from(OtpCode).where(
            OtpCode.phone == phone, OtpCode.created_at > utcnow() - timedelta(hours=1)))
        if recent >= 5:
            raise HTTPException(429, "Too many codes requested. Try again in an hour.")
        code = security.new_otp()
        session.add(OtpCode(phone=phone, code_hash=security.hash_otp(phone, code, settings.jwt_secret),
                            expires_at=utcnow() + timedelta(minutes=10)))
        session.commit()
        sent = sms.send(phone, f"Vikri Kavach login code: {code}. Valid for 10 minutes. Do not share it.")
        return {"sent": sent, "dev_code": code if settings.otp_mode == "dev" else None}

    @app.post("/api/auth/otp/verify")
    def otp_verify(body: OtpVerify, response: Response, session: Session = Depends(db)):
        try:
            phone = security.normalise_phone(body.phone)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        otp = session.scalar(select(OtpCode).where(OtpCode.phone == phone, OtpCode.used.is_(False))
                             .order_by(OtpCode.id.desc()).limit(1))
        expires = otp.expires_at.replace(tzinfo=otp.expires_at.tzinfo or timezone.utc) if otp else None
        if not otp or expires < utcnow() or otp.attempts >= 5:
            raise HTTPException(400, "Code expired. Request a new one.")
        otp.attempts += 1
        if not secrets.compare_digest(otp.code_hash, security.hash_otp(phone, body.code, settings.jwt_secret)):
            session.commit()
            raise HTTPException(400, "Wrong code")
        otp.used = True
        user = session.scalar(select(User).where(User.phone == phone))
        if not user:
            user = User(role="farmer", phone=phone)
            session.add(user)
        session.commit()
        set_session(response, user)
        return me_dict(user)

    @app.post("/api/auth/staff/login")
    def staff_login(body: StaffLogin, response: Response, session: Session = Depends(db)):
        user = session.scalar(select(User).where(User.username == body.username.strip().lower(),
                                                 User.role.in_(["officer", "admin"]), User.active.is_(True)))
        if not user or not security.verify_password(body.password, user.password_hash):
            raise HTTPException(401, "Wrong username or password")
        audit(session, user, "login")
        session.commit()
        set_session(response, user)
        return me_dict(user)

    @app.post("/api/auth/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return me_dict(user)

    @app.patch("/api/me")
    def update_me(body: ProfileUpdate, user: User = Depends(current_user), session: Session = Depends(db)):
        u = session.get(User, user.id)
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(u, k, v.strip() if isinstance(v, str) else v)
        session.commit()
        return me_dict(u)

    @app.get("/api/notifications")
    def notifications(user: User = Depends(current_user), session: Session = Depends(db)):
        rows = session.scalars(select(Notification).where(Notification.user_id == user.id)
                               .order_by(Notification.id.desc()).limit(30)).all()
        return [{"id": n.id, "text": n.text, "link": n.link, "read": n.read, "at": n.created_at.isoformat()} for n in rows]

    @app.post("/api/notifications/read")
    def notifications_read(user: User = Depends(current_user), session: Session = Depends(db)):
        for n in session.scalars(select(Notification).where(Notification.user_id == user.id,
                                                            Notification.read.is_(False))):
            n.read = True
        session.commit()
        return {"ok": True}

    # -- farmer: sales -----------------------------------------------------
    @app.post("/api/slips/read")
    async def slip_read(file: UploadFile = File(...), _: User = Depends(farmer)):
        """AI reads a slip photo and returns fields to pre-fill the sale form. Nothing is stored."""
        if state["claude"] is None:
            raise HTTPException(503, "Slip reading is not configured on this server")
        data = await file.read()
        if not data or len(data) > MAX_UPLOAD or not sniff_type(data):
            raise HTTPException(415, "Upload a JPG, PNG, WebP or PDF up to 10 MB")
        try:
            return read_slip(state["claude"], data)
        except Exception as exc:
            log.warning("slip read failed: %s", type(exc).__name__)
            raise HTTPException(422, "Could not read the slip. Fill the form by hand.") from exc

    @app.post("/api/sales")
    def create_sale(body: SaleIn, user: User = Depends(farmer), session: Session = Depends(db)):
        if body.apmc_code not in apmc_by_code():
            raise HTTPException(400, "unknown APMC")
        if body.commodity_code not in MAIN_CROPS:
            raise HTTPException(400, "unknown crop")
        if body.sale_date > today() or body.sale_date < today() - timedelta(days=365):
            raise HTTPException(400, "sale date must be within the last year")
        trader = None
        if body.licence_no.strip():
            trader = session.scalar(select(Trader).where(Trader.apmc_code == body.apmc_code,
                                                         func.lower(Trader.licence_no) == body.licence_no.strip().lower()))
        due = body.payment_due or body.sale_date + timedelta(days=settings.payment_days_default)
        s = Sale(reference="", farmer_id=user.id, apmc_code=body.apmc_code, market_name=body.market_name.strip(),
                 trader_id=trader.id if trader else None, trader_name=body.trader_name.strip(),
                 licence_no=body.licence_no.strip(), commodity_code=body.commodity_code, variety=body.variety.strip(),
                 bags=body.bags, own_weight_qtl=body.own_weight_qtl, slip_weight_qtl=body.slip_weight_qtl,
                 rate_per_qtl=body.rate_per_qtl, gross_amount=body.gross_amount,
                 deductions=[d.model_dump() for d in body.deductions], net_amount=body.net_amount,
                 payment_mode=body.payment_mode, sale_date=body.sale_date, payment_due=due)
        session.add(s)
        session.flush()
        s.reference = f"VK-{body.sale_date.year}-{s.id:06d}"
        recompute_status(s, today())
        audit(session, user, "sale_created", s.reference)
        session.commit()
        s = load_sale(session, s.id)
        return sale_dict(s, checks.check_sale(session, s, settings.weight_tolerance_pct, today()))

    @app.get("/api/sales")
    def list_sales(user: User = Depends(farmer), session: Session = Depends(db)):
        rows = session.scalars(select(Sale).where(Sale.farmer_id == user.id).order_by(Sale.sale_date.desc(), Sale.id.desc())
                               .options(selectinload(Sale.evidence), selectinload(Sale.payments),
                                        selectinload(Sale.trader))).all()
        return [sale_dict(s, checks.check_sale(session, s, settings.weight_tolerance_pct, today())) for s in rows]

    @app.get("/api/sales/{sale_id}")
    def get_sale(sale_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
        s = own_sale(session, sale_id, user)
        out = sale_dict(s, checks.check_sale(session, s, settings.weight_tolerance_pct, today()))
        c = session.scalar(select(Complaint).where(Complaint.sale_id == s.id))
        out["complaint"] = None if not c else {"id": c.id, "reference": c.reference, "status": c.status,
                                               "officer_note": c.officer_note}
        return out

    @app.post("/api/sales/{sale_id}/evidence")
    async def add_evidence(sale_id: int, kind: Literal["patti", "weighbridge", "cheque", "produce", "other"] = Form(...),
                           file: UploadFile = File(...), user: User = Depends(farmer), session: Session = Depends(db)):
        s = own_sale(session, sale_id, user)
        data = await file.read()
        ctype = sniff_type(data or b"")
        if not data or len(data) > MAX_UPLOAD or not ctype:
            raise HTTPException(415, "Upload a JPG, PNG, WebP or PDF up to 10 MB")
        key, sha = storage.put(data, ctype, f"sales/{s.id}")
        session.add(Evidence(sale_id=s.id, kind=kind, storage_key=key, content_type=ctype, sha256=sha))
        audit(session, user, "evidence_added", f"{s.reference} {kind}")
        session.commit()
        return get_sale(sale_id, user, session)

    @app.get("/api/evidence/{evidence_id}")
    def get_evidence(evidence_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
        e = session.get(Evidence, evidence_id)
        if not e:
            raise HTTPException(404)
        own_sale(session, e.sale_id, user)
        return Response(storage.get(e.storage_key), media_type=e.content_type,
                        headers={"Cache-Control": "private, max-age=300"})

    @app.post("/api/sales/{sale_id}/payments")
    def add_payment(sale_id: int, body: PaymentIn, user: User = Depends(farmer), session: Session = Depends(db)):
        s = own_sale(session, sale_id, user)
        session.add(PaymentEvent(sale_id=s.id, kind=body.kind, amount=body.amount, on_date=body.on_date, note=body.note))
        if body.kind == "received":
            s.amount_paid = round(s.amount_paid + body.amount, 2)
        session.flush()
        session.refresh(s)
        recompute_status(s, today())
        audit(session, user, f"payment_{body.kind}", f"{s.reference} {body.amount}")
        session.commit()
        return get_sale(sale_id, user, session)

    @app.post("/api/sales/{sale_id}/complaint")
    def raise_complaint(sale_id: int, body: ComplaintIn, user: User = Depends(farmer), session: Session = Depends(db)):
        s = own_sale(session, sale_id, user)
        cats = [c for c in body.categories if c in COMPLAINT_CATEGORIES]
        if not cats:
            raise HTTPException(400, "choose at least one problem")
        if session.scalar(select(Complaint).where(Complaint.sale_id == s.id)):
            raise HTTPException(409, "a complaint already exists for this sale")
        c = Complaint(reference="", sale_id=s.id, farmer_id=user.id, apmc_code=s.apmc_code, categories=cats,
                      description=body.description.strip())
        session.add(c)
        session.flush()
        c.reference = f"VKC-{c.created_at.year}-{c.id:05d}"
        if s.status != "paid":
            s.status = "disputed" if s.status not in ("overdue", "bounced") else s.status
        for o in session.scalars(select(User).where(User.role == "officer", User.apmc_code == s.apmc_code,
                                                     User.active.is_(True))):
            session.add(Notification(user_id=o.id, link=f"/officer/complaints/{c.id}",
                                     text=f"New complaint {c.reference} on sale {s.reference}: {', '.join(cats)}."))
        audit(session, user, "complaint_raised", c.reference)
        session.commit()
        return {"id": c.id, "reference": c.reference, "status": c.status}

    @app.get("/api/complaints")
    def list_complaints(user: User = Depends(current_user), session: Session = Depends(db)):
        stmt = select(Complaint).order_by(Complaint.id.desc()).options(selectinload(Complaint.sale))
        if user.role == "farmer":
            stmt = stmt.where(Complaint.farmer_id == user.id)
        elif user.role == "officer":
            stmt = stmt.where(Complaint.apmc_code == user.apmc_code)
        return [{"id": c.id, "reference": c.reference, "status": c.status, "categories": c.categories,
                 "sale_id": c.sale_id, "sale_reference": c.sale.reference, "created_at": c.created_at.isoformat(),
                 "officer_note": c.officer_note} for c in session.scalars(stmt.limit(200))]

    @app.get("/api/complaints/{complaint_id}/pack", response_class=HTMLResponse)
    def complaint_pack(complaint_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
        """Printable evidence pack for the APMC secretary: facts, checks, payments and photos."""
        c = session.get(Complaint, complaint_id)
        if not c:
            raise HTTPException(404)
        s = own_sale(session, c.sale_id, user)
        findings = checks.check_sale(session, s, settings.weight_tolerance_pct, today())
        f = session.get(User, s.farmer_id)
        apmc = apmc_by_code().get(s.apmc_code, {})
        rows = [("Complaint", c.reference), ("Filed", c.created_at.strftime("%d %b %Y")),
                ("Problems", ", ".join(c.categories)), ("Farmer", f"{f.name or '-'} ({f.phone})"),
                ("APMC", f"{apmc.get('name_en', s.apmc_code)}, {apmc.get('district_en', '')}"),
                ("Sale", f"{s.reference} on {s.sale_date.isoformat()}"),
                ("Trader", f"{s.trader.name if s.trader else s.trader_name or '-'} (licence {s.licence_no or 'not given'}; "
                           f"{'in register: ' + s.trader.status if s.trader else 'not in register'})"),
                ("Crop", f"{crop_label(s.commodity_code)} {s.variety}".strip()),
                ("Weight", f"slip {s.slip_weight_qtl:g} qtl; farmer's weighbridge {s.own_weight_qtl or '-'} qtl; bags {s.bags or '-'}"),
                ("Rate and amounts", f"Rs {s.rate_per_qtl:,.0f}/qtl; gross Rs {s.gross_amount:,.2f}; net Rs {s.net_amount:,.2f}"),
                ("Deductions", "; ".join(f"{d['label']} Rs {d['amount']:,.2f}" for d in s.deductions) or "none"),
                ("Payment", f"due {s.payment_due.isoformat()}; paid Rs {s.amount_paid:,.2f}; status {s.status}")]
        table = "".join(f"<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in rows)
        found = "".join(f"<li><b>{escape(x['severity'])}</b>: {escape(x['message'])}</li>" for x in findings)
        pays = "".join(f"<li>{p.on_date.isoformat()}: {escape(p.kind)} Rs {p.amount:,.2f} {escape(p.note)}</li>"
                       for p in s.payments) or "<li>None recorded</li>"
        photos = "".join(f"<figure><img src='/api/evidence/{e.id}' alt='{escape(e.kind)}'><figcaption>{escape(e.kind)}, "
                         f"{e.uploaded_at.strftime('%d %b %Y %H:%M')} UTC, SHA-256 {e.sha256[:16]}…</figcaption></figure>"
                         for e in s.evidence if e.content_type.startswith("image/"))
        audit(session, user, "pack_viewed", c.reference)
        session.commit()
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>{escape(c.reference)}</title><style>
body{{font-family:system-ui,'Noto Sans Devanagari',sans-serif;max-width:900px;margin:20px auto;padding:0 16px;color:#111}}
th,td{{text-align:left;padding:6px;border-bottom:1px solid #ddd;vertical-align:top}}th{{width:28%;color:#444}}
table{{border-collapse:collapse;width:100%}}img{{max-width:100%;max-height:420px}}figure{{margin:12px 0}}</style></head><body>
<h1>Complaint {escape(c.reference)}</h1><p>Evidence pack generated by Vikri Kavach on {today().isoformat()}.</p>
<table>{table}</table><h2>Farmer's account</h2><p>{escape(c.description) or '-'}</p><h2>Automatic checks</h2><ul>{found}</ul>
<h2>Payments recorded</h2><ul>{pays}</ul><h2>Photos</h2>{photos or '<p>None</p>'}
<p style="color:#555">Checks compare the farmer's records with the MSAMB price for that day and the APMC licence register.
They are leads for the APMC to verify, not findings of wrongdoing.</p></body></html>"""

    # -- APMC officer --------------------------------------------------------
    @app.get("/api/officer/dashboard")
    def officer_dashboard(user: User = Depends(officer), session: Session = Depends(db)):
        stmt = select(Sale).options(selectinload(Sale.trader), selectinload(Sale.payments), selectinload(Sale.evidence))
        if user.role == "officer":
            stmt = stmt.where(Sale.apmc_code == user.apmc_code)
        sales = session.scalars(stmt).all()
        by_trader: dict[str, dict] = {}
        for s in sales:
            key = s.licence_no or f"(no licence) {s.trader_name}"
            t = by_trader.setdefault(key, {"licence_no": s.licence_no, "name": s.trader.name if s.trader else s.trader_name,
                                           "registered": s.trader is not None, "status": s.trader.status if s.trader else None,
                                           "sales": 0, "overdue_count": 0, "overdue_amount": 0.0, "bounced": 0,
                                           "weight_gap_sales": 0, "low_rate_sales": 0, "complaints": 0})
            t["sales"] += 1
            if s.status in ("overdue", "bounced"):
                t["overdue_count"] += 1
                t["overdue_amount"] += s.net_amount - s.amount_paid
            t["bounced"] += sum(1 for p in s.payments if p.kind == "cheque_bounced")
            codes = {f["code"] for f in checks.check_sale(session, s, settings.weight_tolerance_pct, today())}
            t["weight_gap_sales"] += "weight_gap" in codes
            t["low_rate_sales"] += bool(codes & {"rate_low", "rate_below_min"})
        for c in session.scalars(select(Complaint).options(selectinload(Complaint.sale))
                                 .where(Complaint.apmc_code == user.apmc_code if user.role == "officer" else True)):
            key = c.sale.licence_no or f"(no licence) {c.sale.trader_name}"
            if key in by_trader:
                by_trader[key]["complaints"] += 1
        traders = sorted(by_trader.values(), key=lambda t: (-t["overdue_amount"], -t["weight_gap_sales"], -t["complaints"]))
        for t in traders:
            t["overdue_amount"] = round(t["overdue_amount"], 2)
            t["flag"] = (t["overdue_count"] >= 2 or t["bounced"] >= 1 or t["weight_gap_sales"] >= 2
                         or (t["sales"] >= 4 and t["low_rate_sales"] / t["sales"] >= 0.5))
        open_c = [c for c in list_complaints(user, session) if c["status"] in ("submitted", "under_review")]
        return {"apmc_code": user.apmc_code, "apmc_name": apmc_by_code().get(user.apmc_code or "", {}).get("name_en"),
                "totals": {"sales": len(sales), "overdue_amount": round(sum(t["overdue_amount"] for t in traders), 2),
                           "open_complaints": len(open_c), "flagged_traders": sum(t["flag"] for t in traders)},
                "traders": traders[:100], "open_complaints": open_c[:50],
                "note": "Figures come from farmers' own records and are leads to verify, not findings."}

    @app.get("/api/officer/complaints/{complaint_id}")
    def officer_complaint(complaint_id: int, user: User = Depends(officer), session: Session = Depends(db)):
        c = session.get(Complaint, complaint_id)
        if not c or not in_scope(user, c.apmc_code):
            raise HTTPException(404)
        out = {"id": c.id, "reference": c.reference, "status": c.status, "categories": c.categories,
               "description": c.description, "officer_note": c.officer_note, "created_at": c.created_at.isoformat()}
        out["sale"] = get_sale(c.sale_id, user, session)
        return out

    @app.patch("/api/officer/complaints/{complaint_id}")
    def officer_update_complaint(complaint_id: int, body: ComplaintUpdate, user: User = Depends(officer),
                                 session: Session = Depends(db)):
        c = session.get(Complaint, complaint_id)
        if not c or not in_scope(user, c.apmc_code):
            raise HTTPException(404)
        c.status, c.officer_note = body.status, body.officer_note.strip()
        session.add(Notification(user_id=c.farmer_id, link=f"/sales/{c.sale_id}",
                                 text=f"Your complaint {c.reference} is now {body.status.replace('_', ' ')}."
                                      + (f" Note from APMC: {c.officer_note}" if c.officer_note else "")))
        audit(session, user, f"complaint_{body.status}", c.reference)
        session.commit()
        return {"id": c.id, "status": c.status, "officer_note": c.officer_note}

    @app.get("/api/officer/traders")
    def officer_traders(user: User = Depends(officer), session: Session = Depends(db)):
        stmt = select(Trader).order_by(Trader.name)
        if user.role == "officer":
            stmt = stmt.where(Trader.apmc_code == user.apmc_code)
        return [{"id": t.id, "apmc_code": t.apmc_code, "licence_no": t.licence_no, "name": t.name, "firm": t.firm,
                 "status": t.status, "status_note": t.status_note} for t in session.scalars(stmt)]

    @app.post("/api/officer/traders")
    def officer_upsert_trader(body: TraderIn, user: User = Depends(officer), session: Session = Depends(db)):
        if user.role != "officer" or not user.apmc_code:
            raise HTTPException(403, "only an APMC officer can edit that APMC's register")
        t = session.scalar(select(Trader).where(Trader.apmc_code == user.apmc_code,
                                                func.lower(Trader.licence_no) == body.licence_no.strip().lower()))
        if not t:
            t = Trader(apmc_code=user.apmc_code, licence_no=body.licence_no.strip())
            session.add(t)
        t.name, t.firm, t.status, t.status_note, t.updated_by = (body.name.strip(), body.firm.strip(), body.status,
                                                                  body.status_note.strip(), user.id)
        session.flush()
        for s in session.scalars(select(Sale).where(Sale.apmc_code == user.apmc_code, Sale.trader_id.is_(None),
                                                    func.lower(Sale.licence_no) == t.licence_no.lower())):
            s.trader_id = t.id  # link earlier sales recorded before the trader was registered
        audit(session, user, "trader_saved", f"{t.licence_no} {t.status}")
        session.commit()
        return {"id": t.id, "licence_no": t.licence_no, "status": t.status}

    # -- single-page app -----------------------------------------------------
    static = Path(settings.static_dir) if settings.static_dir else None
    if static and (static / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = (static / path).resolve()
            if path and static.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def build() -> FastAPI:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if os.environ.get("DEMO_APMC_CODE") and os.environ.get("STAFF_PASSWORD"):
        from .cli import main as cli_main

        cli_main(["seed-demo", "--apmc-code", os.environ["DEMO_APMC_CODE"]])  # idempotent
    return create_app()
