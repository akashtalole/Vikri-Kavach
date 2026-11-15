"""Admin command line: create staff accounts, load a licence register, run daily jobs."""

from __future__ import annotations

import argparse
import csv
import getpass
import io
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


def read_text(path: str, region: str) -> str:
    if path.startswith("s3://"):
        import boto3

        bucket, _, key = path[5:].partition("/")
        return boto3.client("s3", region_name=region).get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8-sig")
    with open(path, encoding="utf-8-sig") as fh:
        return fh.read()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vikrikavach")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("create-staff", help="create an APMC officer or admin account")
    s.add_argument("--username", required=True)
    s.add_argument("--role", choices=["officer", "admin"], default="officer")
    s.add_argument("--apmc-code", help="MSAMB full APMC code (required for officers)")
    s.add_argument("--name", default="")
    s.add_argument("--password-hash", help="a scrypt hash from `vikrikavach hash-password` (for remote one-off tasks)")
    h = sub.add_parser("hash-password", help="print a password hash for create-staff --password-hash")
    h.add_argument("--stdin", action="store_true", help="read the password from stdin instead of prompting")
    t = sub.add_parser("import-traders", help="load an APMC licence register CSV: licence_no,name,firm,status")
    t.add_argument("--apmc-code", required=True)
    t.add_argument("csv_path", help="a local path, or s3://bucket/key (used by remote one-off tasks)")
    sub.add_parser("daily", help="run the daily jobs once (prices, overdue payments)")
    d = sub.add_parser("seed-demo", help="demo officer 'demo-officer' and sample licence register entries")
    d.add_argument("--apmc-code", required=True)
    args = p.parse_args(argv)
    if args.cmd == "hash-password":
        password = sys.stdin.readline().rstrip("\n") if args.stdin else getpass.getpass("Password (10+ characters): ")
        try:
            print(security.hash_password(password))
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    settings = load()
    Session = make_sessionmaker(make_engine(settings.database_url))

    with Session() as db:
        if args.cmd == "create-staff":
            if args.role == "officer" and not args.apmc_code:
                print("--apmc-code is required for an officer", file=sys.stderr)
                return 1
            if args.password_hash:
                if not args.password_hash.startswith("scrypt$") or args.password_hash.count("$") != 2:
                    print("--password-hash must come from `vikrikavach hash-password`", file=sys.stderr)
                    return 1
                pw_hash = args.password_hash
            else:
                try:
                    pw_hash = security.hash_password(
                        os.environ.get("STAFF_PASSWORD") or getpass.getpass("Password (10+ characters): "))
                except ValueError as exc:
                    print(exc, file=sys.stderr)
                    return 1
            username = args.username.strip().lower()
            user = db.scalar(select(User).where(User.username == username))
            if user and user.role == "farmer":
                print("that username belongs to a farmer account", file=sys.stderr)
                return 1
            if not user:  # re-running create-staff resets the password and APMC of an existing staff account
                user = User(username=username)
                db.add(user)
            user.role, user.name, user.apmc_code, user.password_hash, user.active = (
                args.role, args.name, args.apmc_code, pw_hash, True)
            db.commit()
            print(json.dumps({"id": user.id, "username": user.username, "role": user.role, "apmc_code": user.apmc_code}))
            return 0
        if args.cmd == "import-traders":
            n = 0
            for row in csv.DictReader(io.StringIO(read_text(args.csv_path, settings.aws_region))):
                lic = (row.get("licence_no") or "").strip()
                if not lic:
                    continue
                status = (row.get("status") or "active").strip().lower()
                if status not in ("active", "suspended", "cancelled"):
                    print(f"skipping {lic}: status must be active, suspended or cancelled", file=sys.stderr)
                    continue
                tr = db.scalar(select(Trader).where(Trader.apmc_code == args.apmc_code,
                                                    func.lower(Trader.licence_no) == lic.lower()))
                if not tr:
                    tr = Trader(apmc_code=args.apmc_code, licence_no=lic)
                    db.add(tr)
                tr.name, tr.firm, tr.status = (row.get("name") or "").strip(), (row.get("firm") or "").strip(), status
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
