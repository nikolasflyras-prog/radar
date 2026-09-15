from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

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
    "chip startup", "semiconductor startup", "stealth startup", "ai startup", "startup policy",
}

_NON_COMPANY_ENTITY_PATTERNS = (
    r"\bpolicy\b", r"\breport\b", r"\bconference\b", r"\bconsortium\b", r"\bmission\b",
    r"\binitiative\b", r"\bprogram\b", r"\bmarket forecast\b", r"\bwhite paper\b",
    r"\bmeeting request\b", r"\barchive\b", r"\bexhibit hall\b", r"\bmailing list\b",
    r"\bsocial media\b", r"\bmap your\b", r"\bopens? in new tab\b", r"\bclick here\b",
    r"\bpress release\b", r"\bwebinar\b", r"\broundup\b", r"\bnewsletter\b",
)

_BAD_AFFILIATION_PATTERNS = (
    r"opens? in new tab", r"click here", r"learn more", r"read more", r"register now",
    r"conference archive", r"meeting request", r"exhibit hall", r"mailing list", r"social media",
    r"map your", r"view program", r"download pdf", r"sister conferences",
)


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


def matched_people(text: str, people: Iterable[str]) -> list[str]:
    return [name for name in people if name and _term_pattern(name).search(text or "")]


def matched_employers(text: str, employers: Iterable[str]) -> list[str]:
    return [name for name in employers if name and _term_pattern(name).search(text or "")]


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


def looks_like_affiliation(value: str) -> bool:
    value = " ".join((value or "").split()).strip(" ,.;:-")
    if not value or len(value) > 100 or len(value.split()) > 10:
        return False
    lower = value.casefold()
    if any(re.search(pattern, lower, re.IGNORECASE) for pattern in _BAD_AFFILIATION_PATTERNS):
        return False
    if not re.search(r"[A-Za-z]", value):
        return False
    return True


def entity_is_financial_vehicle(name: str, context: str = "") -> bool:
    blob = " ".join(f"{name} {context}".split())
    return any(re.search(pattern, blob, re.IGNORECASE) for pattern in _FINANCIAL_VEHICLE_PATTERNS)


def entity_is_excluded(name: str, context: str, excluded_terms: Iterable[str]) -> bool:
    blob = f"{name} {context}".strip()
    return entity_is_financial_vehicle(name, context) or bool(matched_terms(blob, excluded_terms))


def looks_like_company_candidate(name: str) -> bool:
    value = " ".join((name or "").split()).strip(" ,.;:-")
    if not value or value.casefold() in _GENERIC_ENTITY_CANDIDATES:
        return False
    if entity_is_financial_vehicle(value):
        return False
    if any(re.search(pattern, value, re.IGNORECASE) for pattern in _NON_COMPANY_ENTITY_PATTERNS):
        return False
    if len(value.split()) > 6 or len(value) > 80:
        return False
    return bool(re.search(r"[A-Za-z]", value))


def startup_language_matches(text: str, language: Iterable[str]) -> list[str]:
    return matched_terms(text, language)


def classify_public_signal(text: str, keyword_cfg: dict, watchlist_people: Iterable[str] = ()) -> RelevanceClassification:
    strong = tuple(matched_terms(text, keyword_cfg.get("strong_terms", keyword_cfg.get("terms", []))))
    contextual = tuple(matched_terms(text, keyword_cfg.get("contextual_terms", [])))
    startup = tuple(startup_language_matches(text, keyword_cfg.get("startup_language", [])))
    weak_startup = tuple(startup_language_matches(text, keyword_cfg.get("startup_weak_language", [])))
    watched = tuple(matched_people(text, watchlist_people))
    distinct_domain = tuple(dict.fromkeys((*strong, *contextual)))
    has_domain = bool(strong) or len(distinct_domain) >= 2
    if startup and (has_domain or watched):
        category = "spinout"
    elif weak_startup and watched and has_domain:
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
        rf"^{name}\s+(?:raises?|raised|launches?|launched|unveils?|unveiled|forms?|formed|founded|emerges?|emerged|exits?|exited|secures?|secured|closes?|closed|builds?|built|lands?|landed)\b",
        rf"\b(?:startup|spinout|spin-off|company)\s+{name}\s+(?:raises?|launches?|unveils?|emerges?|secures?|is\b)",
        rf"^{name}\s*[:—–-]\s*(?:startup|spinout|stealth|new chip|new silicon|new semiconductor)",
        rf"\b(?:introducing|meet)\s+{name}\b",
        rf"\b{name}\s+(?:comes out of stealth|exits stealth|is emerging from stealth)\b",
        rf"\b(?:launches?|launched|founds?|founded|forms?|formed|unveils?|unveiled)\s+(?:a\s+)?(?:new\s+)?(?:stealth\s+)?(?:startup\s+)?{name}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        candidate = " ".join(match.group(1).split()).strip(" ,.;:-")
        if looks_like_company_candidate(candidate):
            return candidate
    return None


def has_departure_context(text: str, keyword_cfg: dict, employers: Iterable[str] = ()) -> bool:
    movement = keyword_cfg.get("movement_language", [])
    return bool(matched_terms(text, movement) and (matched_employers(text, employers) or matched_terms(text, keyword_cfg.get("strong_terms", []))))


def person_departure_matches(text: str, keyword_cfg: dict, people: Sequence[dict]) -> list[dict]:
    """Watchlist people whose OWN last-known employer co-occurs with departure
    language in *text* — a specific former-employer + departure combination,
    not just any watchlist employer appearing anywhere in the same article."""
    movement = keyword_cfg.get("departure_language") or keyword_cfg.get("movement_language", [])
    if not matched_terms(text, movement):
        return []
    output: list[dict] = []
    for person in people:
        employer = person.get("last_known_employer") or ""
        if not employer or not contains_term(text, employer):
            continue
        names = [person.get("name", ""), *person.get("known_aliases", [])]
        if any(contains_term(text, name) for name in names if name):
            output.append(person)
    return output


def watchlist_identity_matches(text: str, people: Sequence[dict]) -> list[dict]:
    output: list[dict] = []
    for person in people:
        names = [person.get("name", ""), *person.get("known_aliases", [])]
        if any(contains_term(text, name) for name in names if name):
            output.append(person)
    return output


def build_formation_queries(keyword_cfg: dict, orgs: Sequence[dict], *, max_orgs: int = 12) -> list[str]:
    configured = list(keyword_cfg.get("formation_queries", []))
    domain_terms = list(keyword_cfg.get("news_query_domain_terms", [])) or list(keyword_cfg.get("strong_terms", []))[:8]
    movement = list(keyword_cfg.get("news_query_movement_terms", [])) or [
        "startup", "stealth", "founder", "spinout", "left", "former",
    ]
    queries: list[str] = configured[:]
    movement_block = " OR ".join(f'"{term}"' if " " in term else term for term in movement[:8])
    for term in domain_terms[:10]:
        queries.append(f'"{term}" ({movement_block})')
    for org in orgs[:max_orgs]:
        name = org.get("name") if isinstance(org, dict) else str(org)
        if name:
            queries.append(f'"{name}" (founder OR startup OR stealth OR "has left" OR "former {name}")')
    return list(dict.fromkeys(q for q in queries if q.strip()))
