"""Database models (SQLAlchemy 2). PostgreSQL in production, SQLite for development and tests."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, text,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(16), index=True)  # farmer | officer | admin
    phone: Mapped[str | None] = mapped_column(String(16), unique=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(256))
    name: Mapped[str] = mapped_column(String(120), default="")
    language: Mapped[str] = mapped_column(String(4), default="mr")
    village: Mapped[str] = mapped_column(String(120), default="")
    district: Mapped[str] = mapped_column(String(64), default="")
    apmc_code: Mapped[str | None] = mapped_column(String(16), index=True)  # officer's APMC (MSAMB full code)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OtpCode(Base):
    __tablename__ = "otp_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(16), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Trader(Base):
    """Official licence register, maintained by APMC staff. Only this register drives the 'licence' check."""
    __tablename__ = "traders"
    __table_args__ = (UniqueConstraint("apmc_code", "licence_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    apmc_code: Mapped[str] = mapped_column(String(16), index=True)
    licence_no: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    firm: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | suspended | cancelled
    status_note: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(24), unique=True)
    farmer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    apmc_code: Mapped[str] = mapped_column(String(16), index=True)
    market_name: Mapped[str] = mapped_column(String(120))  # as in MSAMB price tables, for the rate check
    trader_id: Mapped[int | None] = mapped_column(ForeignKey("traders.id"), index=True)
    trader_name: Mapped[str] = mapped_column(String(160), default="")
    licence_no: Mapped[str] = mapped_column(String(64), default="")
    commodity_code: Mapped[str] = mapped_column(String(8))
    variety: Mapped[str] = mapped_column(String(64), default="")
    bags: Mapped[int | None] = mapped_column(Integer)
    own_weight_qtl: Mapped[float | None] = mapped_column(Float)  # farmer's independent weighbridge weight
    slip_weight_qtl: Mapped[float] = mapped_column(Float)  # weight on the trader's slip
    rate_per_qtl: Mapped[float] = mapped_column(Float)
    gross_amount: Mapped[float] = mapped_column(Float)
    deductions: Mapped[list] = mapped_column(JSON, default=list)  # [{label, kind, amount}]
    net_amount: Mapped[float] = mapped_column(Float)
    payment_mode: Mapped[str] = mapped_column(String(16), default="not_stated")
    sale_date: Mapped[date] = mapped_column(Date, index=True)
    payment_due: Mapped[date] = mapped_column(Date, index=True)
    amount_paid: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="awaiting_payment", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    farmer: Mapped[User] = relationship()
    trader: Mapped[Trader | None] = relationship()
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="sale", cascade="all, delete-orphan")
    payments: Mapped[list["PaymentEvent"]] = relationship(back_populates="sale", cascade="all, delete-orphan",
                                                          order_by="PaymentEvent.at")


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # patti | weighbridge | cheque | produce | other
    storage_key: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    extracted: Mapped[dict | None] = mapped_column(JSON)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sale: Mapped[Sale] = relationship(back_populates="evidence")


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # received | cheque_bounced | promised
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    on_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sale: Mapped[Sale] = relationship(back_populates="payments")


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(24), unique=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    farmer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    apmc_code: Mapped[str] = mapped_column(String(16), index=True)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="submitted", index=True)
    officer_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    sale: Mapped[Sale] = relationship()


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(String(200), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Price(Base):
    """Daily MSAMB auction prices: the reference for the 'rate' check."""
    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("commodity_code", "market", "variety", "price_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    commodity_code: Mapped[str] = mapped_column(String(8), index=True)
    market: Mapped[str] = mapped_column(String(120), index=True)
    variety: Mapped[str] = mapped_column(String(64), default="")
    price_date: Mapped[date] = mapped_column(Date, index=True)
    arrival: Mapped[float | None] = mapped_column(Float)
    min_price: Mapped[float | None] = mapped_column(Float)
    max_price: Mapped[float | None] = mapped_column(Float)
    modal_price: Mapped[float | None] = mapped_column(Float)


class JobRun(Base):
    """One row per job per day: the unique key stops two containers from running the same daily job."""
    __tablename__ = "job_runs"
    __table_args__ = (UniqueConstraint("job", "run_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(32))
    run_date: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str] = mapped_column(Text, default="")


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_engine(url: str):
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            import os

            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def make_sessionmaker(engine):
    if engine.dialect.name == "postgresql":
        # Several workers and ECS tasks start together; one creates the tables while the others wait.
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(7461001)"))
            Base.metadata.create_all(conn)
    else:
        Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
