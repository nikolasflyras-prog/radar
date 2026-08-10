from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

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


class GdeltNewsCollector(BaseCollector):
    """High-intent public-news search through the GDELT DOC 2.0 API."""

    name = "gdelt"
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    @staticmethod
    def _observed(value: str | None, fallback: datetime) -> datetime:
        if not value:
            return fallback
        try:
            parsed = parse_date(value)
        except Exception:
            return fallback
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        lookback = int(self.config.get("lookback_days", {}).get("gdelt", 14))
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
        queries = list(dict.fromkeys(queries))[: int(search_cfg.get("max_queries", 36))]
        max_records = int(search_cfg.get("records_per_query", 75))
        minimum_seen = since.astimezone(timezone.utc)

        for query in queries:
            params = {
                "query": query, "mode": "ArtList", "format": "json", "maxrecords": max_records,
                "sort": "HybridRel", "timespan": f"{max(1, lookback)}d",
            }
            try:
                payload = self.get(self.endpoint, respect_robots=False, params=params).json()
                articles = payload.get("articles", []) if isinstance(payload, dict) else []
            except Exception as exc:
                result.errors.append(f"{query}: {exc}")
                continue
            result.rows_fetched += len(articles)

            for article in articles:
                title = " ".join(str(article.get("title") or "Untitled").split())
                url = article.get("url")
                domain = article.get("domain") or (urlparse(url).netloc if url else "")
                observed = self._observed(article.get("seendate"), self.utcnow())
                if observed < minimum_seen:
                    continue
                blob = f"{title} {article.get('snippet') or ''}"
                identity_rows = watchlist_identity_matches(blob, people_cfg)
                identity_names = [p["name"] for p in identity_rows]
                classification = classify_public_signal(blob, keyword_cfg, watched_names)
                employer_hits = matched_employers(blob, employers)
                departure_context = has_departure_context(blob, keyword_cfg, employers)
                own_employer_departures = person_departure_matches(blob, keyword_cfg, identity_rows)
                candidate = extract_candidate_entity(title, blob)
                weak_startup = matched_terms(blob, keyword_cfg.get("startup_weak_language", []))
                # "startup" by itself is weak evidence. Promote it only when the headline
                # yields a credible named company plus semiconductor-domain evidence.
                candidate_startup = bool(candidate and weak_startup and classification.domain_terms)
                promoted_spinout = classification.category == "industry" and (departure_context or candidate_startup)

                if own_employer_departures:
                    signal_type, category, base_weight = "news_departure_stealth", "spinout", 20
                elif identity_names and classification.category == "suppressed" and not departure_context:
                    signal_type, category, base_weight = "watchlist_public_mention", "watchlist", 4
                elif classification.category == "spinout" or promoted_spinout:
                    signal_type = "news_watchlist_person" if identity_names else "spinout_discovery"
                    category, base_weight = "spinout", 14 if identity_names else 10
                elif classification.category == "industry":
                    signal_type, category, base_weight = "industry_intelligence", "industry", 0
                else:
                    continue

                raw = dict(article)
                raw.update({
                    "classification": category, "query": query, "candidate_entity": candidate,
                    "matched_strong_terms": list(classification.strong_terms),
                    "matched_contextual_terms": list(classification.contextual_terms),
                    "startup_language": list(classification.startup_terms),
                    "weak_startup_language": weak_startup,
                    "matched_watchlist_people": identity_names,
                    "matched_watchlist_employers": employer_hits,
                    "departure_context": departure_context,
                    "own_employer_departure": [p["name"] for p in own_employer_departures],
                    "publisher_domain": domain,
                })
                result.signals.append(Signal(
                    source=self.name,
                    signal_type=signal_type,
                    entity_name=candidate,
                    person_names=identity_names,
                    observed_at=observed,
                    title=title,
                    url=url,
                    summary=(
                        f"GDELT news discovery from {domain or 'unknown publisher'}; "
                        f"query: {query}; employer matches: {', '.join(employer_hits) or 'none'}"
                    ),
                    raw=raw,
                    base_weight=base_weight,
                    source_key=f"gdelt:{url or title}",
                ))
        return result
