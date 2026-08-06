from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_ORG_PATTERNS = (
    r"\bllc\b", r"\bl\.p\.?\b", r"\blp\b", r"\binc\.?\b", r"\bcorp\.?\b",
    r"\bltd\.?\b", r"\bfund\b", r"\bpartners?\b", r"\bpartnership\b",
    r"\bholdings?\b", r"\bgeneral partner\b", r"\bventures?\b", r"\bcapital\b",
    r"\bcompany\b", r"\bgroup\b", r"\btrust\b", r"\bseries\b", r"\bsicav\b",
)

_FINANCIAL_VEHICLE_PATTERNS = (
    r"\bfixed income\b", r"\bincome trust\b", r"\binvestment trust\b", r"\bcredit\b",
    r"\bdebt\b", r"\bloan\b", r"\bclo\b", r"\betf\b", r"\breit\b",
    r"\basset management\b", r"\binvestment management\b", r"\bportfolio\b",
    r"\bprivate equity\b", r"\bhedge fund\b", r"\bfund\b", r"\btrust\b",
    r"\bgeneral partner\b", r"\blimited partner\b", r"\bcapital partners?\b",
    r"\bpartners? fund\b", r"\bsecurities\b", r"\bmunicipal\b", r"\btreasury\b",
)

_GENERIC_ENTITY_CANDIDATES = {
    "new", "startup", "company", "semiconductor", "silicon", "technology", "technologies",
    "research", "white paper", "show hn", "launch hn", "former", "exclusive", "report",
}


@dataclass(frozen=True)
class RelevanceClassification:
    category: str
    strong_terms: tuple[str, ...]
    contextual_terms: tuple[str, ...]
    startup_terms: tuple[str, ...]
    watchlist_people: tuple[str, ...]

    @property
    def domain_terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.strong_terms, *self.contextual_terms)))


def _term_pattern(term: str) -> re.Pattern[str]:
    pieces = [re.escape(part) for part in re.split(r"[\s\-_/]+", term.strip()) if part]
    body = r"[\s\-_/]+".join(pieces)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


def matched_terms(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if term and _term_pattern(term).search(text or "")]


def contains_term(text: str, term: str) -> bool:
    return bool(term and _term_pattern(term).search(text or ""))


def looks_like_organization(name: str) -> bool:
    value = " ".join((name or "").split())
    if not value:
        return False
    return any(re.search(pattern, value, re.IGNORECASE) for pattern in _ORG_PATTERNS)


def looks_like_person(name: str) -> bool:
    value = " ".join((name or "").split()).strip(" ,.;")
    if not value or looks_like_organization(value):
        return False
    if any(ch.isdigit() for ch in value) or "/" in value or "@" in value:
        return False
    parts = value.split()
    if not 2 <= len(parts) <= 5:
        return False
    return all(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ.'\-]+", part) for part in parts)


def entity_is_financial_vehicle(name: str, context: str = "") -> bool:
    blob = " ".join(f"{name} {context}".split())
    return any(re.search(pattern, blob, re.IGNORECASE) for pattern in _FINANCIAL_VEHICLE_PATTERNS)


def entity_is_excluded(name: str, context: str, excluded_terms: Iterable[str]) -> bool:
    blob = f"{name} {context}".strip()
    return entity_is_financial_vehicle(name, context) or bool(matched_terms(blob, excluded_terms))


def startup_language_matches(text: str, language: Iterable[str]) -> list[str]:
    return matched_terms(text, language)


def classify_public_signal(text: str, keyword_cfg: dict, watchlist_people: Iterable[str] = ()) -> RelevanceClassification:
    strong = tuple(matched_terms(text, keyword_cfg.get("strong_terms", keyword_cfg.get("terms", []))))
    contextual = tuple(matched_terms(text, keyword_cfg.get("contextual_terms", [])))
    startup = tuple(startup_language_matches(text, keyword_cfg.get("startup_language", [])))
    watched = tuple(name for name in watchlist_people if name and name.casefold() in (text or "").casefold())
    distinct_domain = tuple(dict.fromkeys((*strong, *contextual)))
    has_domain = bool(strong) or len(distinct_domain) >= 2
    if startup and (has_domain or watched):
        category = "spinout"
    elif strong or len(distinct_domain) >= 2:
        category = "industry"
    else:
        category = "suppressed"
    return RelevanceClassification(category, strong, contextual, startup, watched)


def extract_candidate_entity(title: str, body: str = "") -> str | None:
    text = " ".join((title or "").split())
    if not text:
        return None
    token = r"[A-Z][A-Za-z0-9&.'’\-]*"
    name = rf"({token}(?:\s+{token}){{0,5}})"
    patterns = (
        rf"^{name}\s+(?:raises?|raised|launches?|launched|unveils?|unveiled|forms?|formed|founded|emerges?|emerged|exits?|exited|secures?|secured|closes?|closed|builds?|built)\b",
        rf"\b(?:startup|spinout|spin-off|company)\s+{name}\s+(?:raises?|launches?|unveils?|emerges?|secures?|is\b)",
        rf"^{name}\s*[:—–-]\s*(?:startup|spinout|stealth|new chip|new silicon|new semiconductor)",
        rf"\b(?:introducing|meet)\s+{name}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        candidate = " ".join(match.group(1).split()).strip(" ,.;:-")
        if candidate.casefold() in _GENERIC_ENTITY_CANDIDATES:
            continue
        if 1 <= len(candidate.split()) <= 6 and not entity_is_financial_vehicle(candidate):
            return candidate
    return None
