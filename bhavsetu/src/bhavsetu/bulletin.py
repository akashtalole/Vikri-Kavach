"""Daily Marathi market bulletin for a district, written by Claude from computed facts.

Every number in the bulletin must come from the facts. After generation, all numbers in the text (Devanagari or
Latin digits) are checked against the facts; if any is unknown the model is asked once to fix it, and if it still
fails a plain template bulletin is used instead. So a farmer never reads a price the data does not contain.
"""

from __future__ import annotations

import json
import re

from .analytics import district_facts
from .catalog import MAIN_CROPS, crop_label
from .llm import Claude
from .store import Store

DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

SYSTEM = """You write a short daily market bulletin in simple Marathi for farmers in one district of Maharashtra,
to be sent on WhatsApp. Use only the facts given. Every number you write must appear in the facts exactly (you may
write it with or without thousands separators). Do not predict prices or advise anyone to hold or sell; you may say
where prices were higher today and where arrivals were unusually heavy. Mention that prices depend on quality.
At most 150 words, no headings, no tables."""


def numbers_in(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in NUMBER.findall(text.translate(DEVANAGARI))}


def allowed_numbers(facts: list[dict]) -> set[str]:
    out: set[str] = set()
    for f in facts:
        for k, v in f.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out |= {f"{v:g}", f"{abs(v):g}", str(int(round(abs(v))))}
            if k == "date":
                y, m, d = v.split("-")
                out |= {y, m, d, str(int(m)), str(int(d))}
    return out


def template_bulletin(district: str, facts: list[dict]) -> str:
    if not facts:
        return f"{district}: आज बाजारभावाची माहिती उपलब्ध नाही."
    lines = [f"{district} बाजारभाव ({facts[0]['date']}), रु. प्रति क्विंटल:"]
    for f in facts:
        line = (f"{crop_label(f['commodity_code'])}: सर्वाधिक {f['highest_modal']} ({f['highest_market']}), "
                f"सर्वात कमी {f['lowest_modal']} ({f['lowest_market']}).")
        if f["glut_markets"]:
            line += f" जास्त आवक: {', '.join(f['glut_markets'])}."
        lines.append(line)
    lines.append("दर मालाच्या प्रतीनुसार बदलतात. स्रोत: महाराष्ट्र राज्य कृषी पणन मंडळ.")
    return "\n".join(lines)


def make_bulletin(claude: Claude | None, store: Store, district: str, commodities: list[str] | None = None) -> dict:
    facts = district_facts(store, district, commodities or list(MAIN_CROPS))
    for f in facts:
        f["crop"] = crop_label(f["commodity_code"])
    result = {"district": district, "facts": facts, "method": "template", "unverified_numbers": []}
    if not facts or claude is None:
        result["text"] = template_bulletin(district, facts)
        return result
    allowed = allowed_numbers(facts)
    messages = [{"role": "user", "content": "District: " + district + "\nFACTS (prices in Rs per quintal; "
                 "average_change_pct compares today with the average of earlier days):\n"
                 + json.dumps(facts, ensure_ascii=False, indent=1)}]
    for attempt in range(2):
        try:
            text = claude.text(messages, effort="low", system=SYSTEM)
        except Exception as exc:  # network, credentials, refusal: never block the bulletin on the AI step
            result.update(text=template_bulletin(district, facts), method="template_ai_unavailable", error=type(exc).__name__)
            return result
        bad = sorted(numbers_in(text) - allowed)
        if not bad:
            result.update(text=text, method="ai_verified", attempts=attempt + 1)
            return result
        result["unverified_numbers"] = bad
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "These numbers are not in the facts: " + ", ".join(bad)
                      + ". Rewrite the bulletin using only numbers from the facts."}]
    result["text"] = template_bulletin(district, facts)
    result["method"] = "template_after_failed_check"
    return result
