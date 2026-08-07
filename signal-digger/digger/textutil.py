from __future__ import annotations

import re

MA_KEYWORDS = [
    "acquire", "acquires", "acquired", "acquisition", "merger", "merges", "to merge",
    "definitive agreement", "combine with", "combination with", "buyout", "takeover",
    "divest", "divestiture", "spin-off", "spinoff", "asset purchase", "stock purchase",
    "tender offer", "going private",
]

DEPARTURE_KEYWORDS = [
    "joins", "has joined", "steps down", "stepping down", "departs", "departure",
    "resigns", "resignation", "named ceo", "named cto", "appointed", "promoted to",
    "founding engineer", "founding member", "co-founder", "leaves to", "left to join",
]


def normalize(value: str) -> str:
    value = (value or "").casefold().strip()
    value = re.sub(r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|co|company)\b\.?", "", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def contains_term(text: str, term: str) -> bool:
    if not term:
        return False
    return re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE) is not None


def matched_terms(text: str, terms: list[str]) -> list[str]:
    return [t for t in terms if contains_term(text, t)]


def mentions_target(text: str, query: str) -> bool:
    return contains_term(text, query) or normalize(query) in normalize(text)


def classify_ma_or_general(text: str) -> tuple[str, list[str]]:
    """M&A keyword hits promote a news item to the ma_deal bucket; otherwise it's
    a general mention. Shared by every news source so both buckets read the same
    keyword list."""
    hits = matched_terms(text, MA_KEYWORDS)
    return ("ma_deal", hits) if hits else ("general_signal", [])
