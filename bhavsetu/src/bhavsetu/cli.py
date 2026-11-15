"""Command line: ingest MSAMB prices, rebuild the APMC master, serve the app, print a bulletin."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .catalog import MAIN_CROPS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bhavsetu")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest", help="fetch the last week of MSAMB prices for the main crops (run daily)")
    ing.add_argument("--crops", help="comma-separated MSAMB codes; default: all main crops")
    sub.add_parser("harvest-apmcs", help="rebuild data/apmc_master.json from MSAMB profiles and OpenStreetMap")
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8200)
    b = sub.add_parser("bulletin", help="print a district bulletin")
    b.add_argument("district")
    b.add_argument("--no-ai", action="store_true")
    args = parser.parse_args(argv)
    db = os.environ.get("BHAVSETU_DB", "var/bhavsetu.db")

    if args.cmd == "ingest":
        from .msamb import MsambClient, MsambError
        from .store import Store

        store, client = Store(db), MsambClient()
        codes = args.crops.split(",") if args.crops else list(MAIN_CROPS)
        failed = 0
        for code in codes:
            try:
                n = store.upsert_prices(code, client.prices(code))
                store.log_run(code, n)
                print(f"{code} {MAIN_CROPS.get(code, ('', ''))[0]:<22} {n} rows")
            except (MsambError, OSError) as exc:
                failed += 1
                store.log_run(code, 0, str(exc))
                print(f"{code} failed: {exc}", file=sys.stderr)
        return 1 if failed == len(codes) else 0
    if args.cmd == "harvest-apmcs":
        from .harvest import build

        build(Path(__file__).parent / "data" / "apmc_master.json")
        return 0
    if args.cmd == "serve":
        import uvicorn

        from .web import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port)
        return 0
    from .bulletin import make_bulletin
    from .store import Store

    claude = None
    if not args.no_ai:
        from .llm import Claude

        claude = Claude()
    result = make_bulletin(claude, Store(db), args.district)
    print(result["text"])
    print(json.dumps({"method": result["method"], "unverified_numbers": result["unverified_numbers"]}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
