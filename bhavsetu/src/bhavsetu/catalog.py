"""Main crops tracked by default, with MSAMB commodity codes, and the APMC master list (bundled data)."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from importlib import resources
from pathlib import Path

# MSAMB commodity code -> (English, Marathi). Codes as listed on msamb.com's price page.
MAIN_CROPS: dict[str, tuple[str, str]] = {
    "08035": ("Onion", "कांदा"),
    "04017": ("Soybean", "सोयाबिन"),
    "01001": ("Cotton", "कापूस"),
    "03020": ("Tur (pigeon pea)", "तूर"),
    "03006": ("Gram (chana)", "हरभरा"),
    "02009": ("Wheat", "गहू"),
    "02011": ("Jowar", "ज्वारी"),
    "02002": ("Bajra", "बाजरी"),
    "02015": ("Maize", "मका"),
    "03016": ("Moong", "मूग"),
    "03022": ("Urad", "उडीद"),
    "04003": ("Groundnut (dry pods)", "भुईमुग शेंग (सुकी)"),
    "10006": ("Turmeric", "हळद/ हळकुंड"),
    "08071": ("Tomato", "टोमॅटो"),
    "08007": ("Potato", "बटाटा"),
    "08045": ("Garlic", "लसूण"),
    "07007": ("Pomegranate", "डाळींब"),
    "07008": ("Grapes", "द्राक्ष"),
    "07014": ("Banana", "केळी"),
    "07027": ("Orange", "संत्री"),
    "07016": ("Mosambi", "मोसंबी"),
    "10013": ("Green chilli", "मिरची (हिरवी)"),
}


def crop_label(code: str, fallback: str = "") -> str:
    en, mr = MAIN_CROPS.get(code, ("", fallback))
    return f"{mr} ({en})" if en else (mr or code)


@lru_cache(maxsize=1)
def apmc_master() -> dict:
    override = os.environ.get("BHAVSETU_APMC_MASTER")
    path = Path(override) if override else resources.files("bhavsetu").joinpath("data/apmc_master.json")
    if not path.is_file():
        return {"apmcs": [], "price_markets": []}
    return json.loads(path.read_text(encoding="utf-8"))


def reload_master() -> None:
    apmc_master.cache_clear()
    market_index.cache_clear()


def _norm(name: str) -> str:
    return re.sub(r"[\s\-–()\.]+", "", name)


@lru_cache(maxsize=1)
def market_index() -> dict[str, dict]:
    """Map a price-table market name (Marathi) to its APMC record (district, coordinates).

    Price tables name main yards and sub-yards. Each has a short code; sub-yard codes extend the parent's
    three-digit code (for example 01001 is a sub-yard of 010), which matches the APMC profile's short code.
    """
    master = apmc_master()
    by_code = {a.get("code"): a for a in master["apmcs"] if a.get("code")}
    by_name = {_norm(a["name_mr"]): a for a in master["apmcs"]}
    index: dict[str, dict] = {}
    for m in master.get("price_markets", []):
        apmc = by_code.get(m["code"]) or by_code.get(m["code"][:3])
        if apmc:
            index[_norm(m["name_mr"])] = apmc
    for key, apmc in by_name.items():
        index.setdefault(key, apmc)
    return index


def apmc_for_market(market_name: str) -> dict | None:
    index = market_index()
    key = _norm(market_name)
    if key in index:
        return index[key]
    base = re.split(r"[-–(]", market_name)[0]
    return index.get(_norm(base))
