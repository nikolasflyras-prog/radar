from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from .base import BaseCollector
from ..models import CollectorResult, Signal
from ..relevance import classify_public_signal, extract_candidate_entity, matched_terms, watchlist_identity_matches


class HNAlgoliaCollector(BaseCollector):
    name = "hn"

    def _watchlist_queries(self) -> list[str]:
        people = self.config.get("people", [])
        prior = [p for p in people if "prior_founder" in p.get("specialty_tags", [])]
        pool = prior or people
        limit = int(self.config.get("news_search", {}).get("hn_watchlist_query_limit", 20))
        if not pool or limit <= 0:
            return []
        week = self.utcnow().isocalendar().week
        offset = (week * limit) % len(pool)
        rotated = pool[offset:] + pool[:offset]
        return [p["name"] for p in rotated[:limit] if p.get("name")]

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("hn", 14)))
        keyword_cfg = self.config.get("keywords", {})
        people_cfg = self.config.get("people", [])
        watched_names = [p.get("name", "") for p in people_cfg]
        terms = list(keyword_cfg.get("hn_terms", []))
        terms += list(keyword_cfg.get("hn_formation_terms", []))
        terms += self._watchlist_queries()
        queries = list(dict.fromkeys(q for q in terms if q))
        max_queries = int(self.config.get("news_search", {}).get("hn_max_queries", 60))

        for query in queries[:max_queries]:
            url = (
                "https://hn.algolia.com/api/v1/search_by_date"
                f"?query={quote(query)}&tags=story&numericFilters=created_at_i>{int(since.timestamp())}&hitsPerPage=100"
            )
            try:
                hits = self.get(url, respect_robots=False).json().get("hits", [])
            except Exception as exc:
                result.errors.append(f"{query}: {exc}")
                continue
            result.rows_fetched += len(hits)

            for hit in hits:
                title = " ".join(str(hit.get("title") or hit.get("story_title") or "Untitled").split())
                body = str(hit.get("story_text") or "")
                text = f"{title} {body}"
                identities = watchlist_identity_matches(text, people_cfg)
                people = [p["name"] for p in identities]
                classification = classify_public_signal(text, keyword_cfg, watched_names)
                candidate = extract_candidate_entity(title, body)
                weak_startup = matched_terms(text, keyword_cfg.get("startup_weak_language", []))
                promoted_spinout = bool(
                    classification.category == "industry" and candidate and weak_startup and classification.domain_terms
                )

                if people and (classification.category == "spinout" or promoted_spinout):
                    signal_type, category, weight = "hn_watchlist_person", "spinout", 12
                elif people:
                    signal_type, category, weight = "watchlist_public_mention", "watchlist", 4
                elif classification.category == "spinout" or promoted_spinout:
                    signal_type, category, weight = "spinout_discovery", "spinout", 9
                elif classification.category == "industry":
                    signal_type, category, weight = "industry_intelligence", "industry", 0
                else:
                    continue

                raw = dict(hit)
                raw.update({
                    "classification": category,
                    "query": query,
                    "candidate_entity": candidate,
                    "matched_strong_terms": list(classification.strong_terms),
                    "matched_contextual_terms": list(classification.contextual_terms),
                    "startup_language": list(classification.startup_terms),
                    "weak_startup_language": weak_startup,
                    "matched_watchlist_people": people,
                    "points": hit.get("points") or 0,
                })
                observed = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
                result.signals.append(Signal(
                    source=self.name,
                    signal_type=signal_type,
                    entity_name=candidate,
                    observed_at=observed,
                    title=title,
                    person_names=people,
                    url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                    summary=f"HN story matched '{query}' by {hit.get('author')}; {hit.get('points') or 0} points",
                    raw=raw,
                    base_weight=weight,
                    source_key=f"hn:{hit.get('objectID')}",
                ))
        return result
