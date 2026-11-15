"""Admin command line: create staff accounts, load a licence register, run daily jobs."""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import sys

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from . import security
from .config import load
from .jobs import run_daily
from .models import Trader, User, make_engine, make_sessionmaker

# Sample entries for demonstrations only; real deployments load the APMC's own register with import-traders.
DEMO_TRADERS = [("DEMO-101", "Demo Traders A", "active", ""), ("DEMO-102", "Demo Traders B", "active", ""),
                ("DEMO-201", "Demo Traders C", "suspended", "Demo: licence suspended for unpaid farmer dues")]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vikrikavach")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("create-staff", help="create an APMC officer or admin account")
    s.add_argument("--username", required=True)
    s.add_argument("--role", choices=["officer", "admin"], default="officer")
    s.add_argument("--apmc-code", help="MSAMB full APMC code (required for officers)")
    s.add_argument("--name", default="")
    t = sub.add_parser("import-traders", help="load an APMC licence register CSV: licence_no,name,firm,status")
    t.add_argument("--apmc-code", required=True)
    t.add_argument("csv_path")
    sub.add_parser("daily", help="run the daily jobs once (prices, overdue payments)")
    d = sub.add_parser("seed-demo", help="demo officer 'demo-officer' and sample licence register entries")
    d.add_argument("--apmc-code", required=True)
    args = p.parse_args(argv)
    settings = load()
    Session = make_sessionmaker(make_engine(settings.database_url))

    with Session() as db:
        if args.cmd == "create-staff":
            if args.role == "officer" and not args.apmc_code:
                print("--apmc-code is required for an officer", file=sys.stderr)
                return 1
            password = os.environ.get("STAFF_PASSWORD") or getpass.getpass("Password (10+ characters): ")
            try:
                user = User(role=args.role, username=args.username.strip().lower(), name=args.name,
                            apmc_code=args.apmc_code, password_hash=security.hash_password(password))
            except ValueError as exc:
                print(exc, file=sys.stderr)
                return 1
            db.add(user)
            db.commit()
            print(json.dumps({"id": user.id, "username": user.username, "role": user.role, "apmc_code": user.apmc_code}))
            return 0
        if args.cmd == "import-traders":
            n = 0
            with open(args.csv_path, newline="", encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    lic = (row.get("licence_no") or "").strip()
                    if not lic:
                        continue
                    tr = db.scalar(select(Trader).where(Trader.apmc_code == args.apmc_code,
                                                        func.lower(Trader.licence_no) == lic.lower()))
                    if not tr:
                        tr = Trader(apmc_code=args.apmc_code, licence_no=lic)
                        db.add(tr)
                    tr.name, tr.firm = (row.get("name") or "").strip(), (row.get("firm") or "").strip()
                    tr.status = (row.get("status") or "active").strip().lower()
                    n += 1
            db.commit()
            print(json.dumps({"imported": n}))
            return 0
        if args.cmd == "seed-demo":
            password = os.environ.get("STAFF_PASSWORD", "")
            if len(password) < 10:
                print("set STAFF_PASSWORD (10+ characters) for the demo officer", file=sys.stderr)
                return 1
            try:
                if db.bind.dialect.name == "postgresql":  # several workers start at once: seed one at a time
                    db.execute(text("SELECT pg_advisory_xact_lock(7461002)"))
                if not db.scalar(select(User).where(User.username == "demo-officer")):
                    db.add(User(role="officer", username="demo-officer", name="Demo APMC officer",
                                apmc_code=args.apmc_code, password_hash=security.hash_password(password)))
                for lic, name, status, note in DEMO_TRADERS:
                    if not db.scalar(select(Trader).where(Trader.apmc_code == args.apmc_code, Trader.licence_no == lic)):
                        db.add(Trader(apmc_code=args.apmc_code, licence_no=lic, name=name, status=status,
                                      status_note=note))
                db.commit()
            except IntegrityError:  # another process seeded first (SQLite has no advisory lock)
                db.rollback()
            print(json.dumps({"officer": "demo-officer", "traders": len(DEMO_TRADERS), "apmc_code": args.apmc_code}))
            return 0
    print(json.dumps(run_daily(Session), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
