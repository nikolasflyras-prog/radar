from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import feedparser
from dateutil.parser import parse as parse_date

from .base import BaseCollector
from ..models import CollectorResult, Signal
from ..relevance import (
    build_formation_queries,
    classify_public_signal,
    extract_candidate_entity,
    matched_employers,
    matched_terms,
    has_departure_context,
    person_departure_matches,
    watchlist_identity_matches,
)


class GoogleNewsRSSCollector(BaseCollector):
    """Broad public-news search across arbitrary publishers via Google News'
    public RSS search feed.

    GDELT and the curated feed list are both bounded (GDELT by its own index,
    the feed list by whichever publishers are configured). This collector adds
    a third, differently-biased public search surface so a formation story
    from a publisher nobody has configured can still surface. It respects
    robots.txt like the curated feed list (unlike GDELT/HN, which are treated
    as programmatic APIs) since Google News RSS is a page-search endpoint, not
    a documented API; if robots.txt disallows it, the source fails soft.
    """

    name = "googlenews"
    endpoint = "https://news.google.com/rss/search"

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        lookback = int(self.config.get("lookback_days", {}).get("googlenews", 14))
        since = since or self.utcnow() - timedelta(days=lookback)
        keyword_cfg = self.config.get("keywords", {})
        people_cfg = self.config.get("people", [])
        watched_names = [p.get("name", "") for p in people_cfg]
        employers = list(dict.fromkeys(p.get("last_known_employer") for p in people_cfg if p.get("last_known_employer")))
        search_cfg = self.config.get("news_search", {})
        queries = build_formation_queries(
            keyword_cfg, self.config.get("orgs", []),
            max_orgs=int(search_cfg.get("max_employer_queries", 12)),
        )
        prior = [p for p in people_cfg if "prior_founder" in p.get("specialty_tags", [])] or people_cfg
        people_limit = int(search_cfg.get("watchlist_people_queries", 12))
        if prior and people_limit > 0:
            offset = (self.utcnow().isocalendar().week * people_limit) % len(prior)
            for person in (prior[offset:] + prior[:offset])[:people_limit]:
                queries.append(f'"{person["name"]}" (startup OR stealth OR founder OR "has left" OR former)')
        max_queries = int(search_cfg.get("googlenews_max_queries", search_cfg.get("max_queries", 36)))
        queries = list(dict.fromkeys(queries))[:max_queries]

        for query in queries:
            url = f"{self.endpoint}?q={quote(f'{query} when:{lookback}d')}&hl=en-US&gl=US&ceid=US:en"
            try:
                response = self.get(url)
                parsed = feedparser.parse(response.content)
                if parsed.bozo and not parsed.entries:
                    raise ValueError(str(parsed.bozo_exception))
            except Exception as exc:
                result.errors.append(f"{query}: {exc}")
                continue
            result.rows_fetched += len(parsed.entries)

            for entry in parsed.entries:
                title = " ".join(str(entry.get("title") or "Untitled").split())
                source = entry.get("source")
                publisher = source.get("title") if isinstance(source, dict) else ""
                blob = f"{title} {entry.get('summary', '')}"
                try:
                    observed = parse_date(entry.get("published") or entry.get("updated"))
                except Exception:
                    observed = self.utcnow()
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                observed = observed.astimezone(timezone.utc)
                if observed < since:
                    continue

                identity_rows = watchlist_identity_matches(blob, people_cfg)
                people = [p["name"] for p in identity_rows]
                classification = classify_public_signal(blob, keyword_cfg, watched_names)
                employer_hits = matched_employers(blob, employers)
                departure_context = has_departure_context(blob, keyword_cfg, employers)
                own_employer_departures = person_departure_matches(blob, keyword_cfg, identity_rows)
                candidate = extract_candidate_entity(title, blob)
                weak_startup = matched_terms(blob, keyword_cfg.get("startup_weak_language", []))
                candidate_startup = bool(candidate and weak_startup and classification.domain_terms)
                promoted_spinout = classification.category == "industry" and (departure_context or candidate_startup)

                if own_employer_departures:
                    signal_type, category, weight = "news_departure_stealth", "spinout", 20
                elif people and (classification.category == "spinout" or promoted_spinout):
                    signal_type, category, weight = "news_watchlist_person", "spinout", 14
                elif people:
                    signal_type, category, weight = "watchlist_public_mention", "watchlist", 4
                elif classification.category == "spinout" or promoted_spinout:
                    signal_type, category, weight = "spinout_discovery", "spinout", 10
                elif classification.category == "industry":
                    signal_type, category, weight = "industry_intelligence", "industry", 0
                else:
                    continue

                raw = dict(entry)
                raw.update({
                    "classification": category,
                    "query": query,
                    "candidate_entity": candidate,
                    "matched_strong_terms": list(classification.strong_terms),
                    "matched_contextual_terms": list(classification.contextual_terms),
                    "startup_language": list(classification.startup_terms),
                    "weak_startup_language": weak_startup,
                    "matched_watchlist_people": people,
                    "matched_watchlist_employers": employer_hits,
                    "departure_context": departure_context,
                    "own_employer_departure": [p["name"] for p in own_employer_departures],
                    "publisher": publisher,
                })
                result.signals.append(Signal(
                    source=self.name,
                    signal_type=signal_type,
                    entity_name=candidate,
                    person_names=people,
                    title=title,
                    observed_at=observed,
                    url=entry.get("link"),
                    summary=f"Google News ({publisher or 'unknown publisher'}): {category}; employer matches: {', '.join(employer_hits) or 'none'}",
                    raw=raw,
                    base_weight=weight,
                    source_key=f"googlenews:{entry.get('id') or entry.get('link')}",
                ))
        return result
