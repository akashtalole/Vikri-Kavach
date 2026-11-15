"""Daily jobs: ingest MSAMB prices, mark overdue payments and notify farmers. Safe to run on many containers:
each job runs once per day, guarded by a unique (job, date) row."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta, timezone

from bhavsetu.catalog import MAIN_CROPS
from bhavsetu.msamb import MsambClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import JobRun, Notification, Price, Sale

log = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def today_ist() -> date:
    return datetime.now(IST).date()


STALE_AFTER = timedelta(minutes=30)


def claim(db: Session, job: str, day: date) -> bool:
    """Take today's run of a job. A claim left unfinished for 30 minutes (its container died) can be taken over."""
    db.add(JobRun(job=job, run_date=day))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
    run = db.scalar(select(JobRun).where(JobRun.job == job, JobRun.run_date == day).with_for_update())
    started = run.started_at.replace(tzinfo=run.started_at.tzinfo or timezone.utc) if run else None
    if run and run.finished_at is None and started < datetime.now(timezone.utc) - STALE_AFTER:
        run.started_at = datetime.now(timezone.utc)
        db.commit()
        return True
    db.rollback()
    return False


def finish(db: Session, job: str, day: date, result) -> None:
    run = db.scalar(select(JobRun).where(JobRun.job == job, JobRun.run_date == day))
    run.finished_at, run.result = datetime.now(timezone.utc), str(result)[:4000]
    db.commit()


def upsert_prices(db: Session, commodity: str, rows) -> int:
    if not rows:
        return 0
    # MSAMB can list the same market, variety and date twice; keep the last row so one upsert touches each key once.
    by_key = {(r.market, r.variety, r.price_date): r for r in rows}
    values = [{"commodity_code": commodity, "market": r.market, "variety": r.variety, "price_date": r.price_date,
               "arrival": r.arrival, "min_price": r.min_price, "max_price": r.max_price, "modal_price": r.modal_price}
              for r in by_key.values()]
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    stmt = insert(Price).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["commodity_code", "market", "variety", "price_date"],
        set_={k: getattr(stmt.excluded, k) for k in ("arrival", "min_price", "max_price", "modal_price")})
    db.execute(stmt)
    db.commit()
    return len(values)


def ingest_prices(db: Session, client: MsambClient | None = None, crops: list[str] | None = None) -> dict:
    client = client or MsambClient()
    result = {}
    for code in crops or list(MAIN_CROPS):
        try:
            result[code] = upsert_prices(db, code, client.prices(code))
        except Exception as exc:  # one crop failing must not stop the others
            db.rollback()
            log.warning("price ingest failed for %s: %s", code, type(exc).__name__)
            result[code] = f"error: {type(exc).__name__}"
    return result


def mark_overdue(db: Session, day: date) -> int:
    """Sales past their due date with money outstanding become overdue; the farmer is told once."""
    sales = db.scalars(select(Sale).where(Sale.status.in_(["awaiting_payment", "partly_paid"]),
                                          Sale.payment_due < day)).all()
    for s in sales:
        s.status = "overdue"
        db.add(Notification(user_id=s.farmer_id, link=f"/sales/{s.id}",
                            text=f"Payment for sale {s.reference} is overdue: Rs {s.net_amount - s.amount_paid:,.0f} "
                                 f"unpaid since {s.payment_due.isoformat()}. You can raise a complaint from the sale page."))
    db.commit()
    return len(sales)


def run_daily(Session: sessionmaker, client: MsambClient | None = None, day: date | None = None) -> dict:
    day = day or today_ist()
    out = {}
    with Session() as db:
        if claim(db, "overdue", day):
            out["overdue_marked"] = mark_overdue(db, day)
            finish(db, "overdue", day, out["overdue_marked"])
        if claim(db, "prices", day):
            out["prices"] = ingest_prices(db, client)
            finish(db, "prices", day, out["prices"])
    return out


class Scheduler:
    """Hourly check in a background thread; each daily job still runs only once per day across all tasks."""

    def __init__(self, Session: sessionmaker, interval_seconds: int = 3600):
        self.Session, self.interval = Session, interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                result = run_daily(self.Session)
                if result:
                    log.info("daily jobs: %s", result)
            except Exception:
                log.exception("daily jobs failed")
            self._stop.wait(self.interval)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="vk-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
