"""Build data/apmc_master.json: every APMC with district, address, PIN code and coordinates.

Coordinates come from OpenStreetMap Nominatim (data (c) OpenStreetMap contributors, ODbL), looked up by the APMC's
PIN code, falling back to "<APMC>, <district>, Maharashtra". One request per second, per Nominatim's usage policy.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

from .msamb import USER_AGENT, MsambClient, MsambError

NOMINATIM = "https://nominatim.openstreetmap.org/search"


def geocode(http: httpx.Client, **params) -> tuple[float, float] | None:
    time.sleep(1.1)
    resp = http.get(NOMINATIM, params={"format": "json", "limit": 1, "countrycodes": "in", **params})
    if resp.status_code != 200:
        return None
    hits = resp.json()
    return (float(hits[0]["lat"]), float(hits[0]["lon"])) if hits else None


def in_maharashtra(lat: float, lon: float) -> bool:
    return 15.5 <= lat <= 22.2 and 72.5 <= lon <= 81.0


def build(out: Path, client: MsambClient | None = None) -> dict:
    client = client or MsambClient(pause_seconds=0.6)
    geo = httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})
    districts = client.districts()
    price_markets = client.price_markets()
    apmcs = []
    for d in districts:
        for a in d["apmcs"]:
            item = {"full_code": a["full_code"], "name_en": a["name_en"], "name_mr": a["name_mr"],
                    "district_en": d["name_en"], "district_mr": d["name_mr"]}
            try:
                item.update(client.profile(a["full_code"]))
            except (MsambError, ValueError, httpx.HTTPError) as exc:
                item["profile_error"] = str(exc)
            point, source = None, None
            if item.get("pin_code"):
                point, source = geocode(geo, postalcode=item["pin_code"]), "pin code"
            if not point or not in_maharashtra(*point):
                point, source = geocode(geo, q=f"{a['name_en']}, {d['name_en']}, Maharashtra"), "name"
            if point and in_maharashtra(*point):
                item.update(lat=round(point[0], 5), lon=round(point[1], 5), location_source=f"OpenStreetMap ({source})")
            apmcs.append(item)
            print(f"{len(apmcs):3d} {d['name_en']:<20} {a['name_en']:<28} {item.get('lat', '-')}", flush=True)
    data = {"source": "msamb.com APMC profiles; coordinates (c) OpenStreetMap contributors (ODbL)",
            "generated": time.strftime("%Y-%m-%d"), "apmcs": apmcs, "price_markets": price_markets}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


if __name__ == "__main__":
    build(Path(sys.argv[1]))
