"""SQLite price history. MSAMB shows about a week per call, so daily ingestion builds the longer history."""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from .msamb import PriceRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    commodity_code TEXT NOT NULL,
    market TEXT NOT NULL,
    variety TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    price_date TEXT NOT NULL,
    arrival REAL,
    min_price REAL,
    max_price REAL,
    modal_price REAL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (commodity_code, market, variety, price_date)
);
CREATE INDEX IF NOT EXISTS prices_by_day ON prices (commodity_code, price_date);
CREATE TABLE IF NOT EXISTS ingest_runs (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    commodity_code TEXT NOT NULL,
    rows INTEGER NOT NULL,
    error TEXT
);
"""


class Store:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    def all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def upsert_prices(self, commodity_code: str, rows: list[PriceRow]) -> int:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.lock:
            self.conn.executemany(
                "INSERT INTO prices (commodity_code, market, variety, unit, price_date, arrival, min_price, max_price,"
                " modal_price, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(commodity_code, market, variety, price_date) DO UPDATE SET arrival = excluded.arrival,"
                " min_price = excluded.min_price, max_price = excluded.max_price, modal_price = excluded.modal_price,"
                " unit = excluded.unit, fetched_at = excluded.fetched_at",
                [(commodity_code, r.market, r.variety, r.unit, r.price_date.isoformat(), r.arrival, r.min_price,
                  r.max_price, r.modal_price, now) for r in rows])
            self.conn.commit()
        return len(rows)

    def log_run(self, commodity_code: str, rows: int, error: str | None = None) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO ingest_runs (at, commodity_code, rows, error) VALUES (?, ?, ?, ?)",
                              (datetime.now(timezone.utc).isoformat(timespec="seconds"), commodity_code, rows, error))
            self.conn.commit()

    def latest_date(self, commodity_code: str) -> date | None:
        rows = self.all("SELECT MAX(price_date) AS d FROM prices WHERE commodity_code = ?", (commodity_code,))
        return date.fromisoformat(rows[0]["d"]) if rows and rows[0]["d"] else None

    def day(self, commodity_code: str, day: date) -> list[dict]:
        return self.all("SELECT * FROM prices WHERE commodity_code = ? AND price_date = ? AND modal_price > 0",
                        (commodity_code, day.isoformat()))

    def history(self, commodity_code: str, market: str, variety: str, since: date) -> list[dict]:
        return self.all("SELECT * FROM prices WHERE commodity_code = ? AND market = ? AND variety = ? AND price_date >= ?"
                        " ORDER BY price_date", (commodity_code, market, variety, since.isoformat()))

    def commodities_with_data(self) -> list[str]:
        return [r["commodity_code"] for r in self.all("SELECT DISTINCT commodity_code FROM prices")]
