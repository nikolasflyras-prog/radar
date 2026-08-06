from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import BaseCollector
from ..models import CollectorResult, Signal
from ..relevance import classify_public_signal, extract_candidate_entity, matched_terms


class HNAlgoliaCollector(BaseCollector):
    name = "hn"

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("hn", 14)))
        keyword_cfg = self.config["keywords"]
        terms = list(dict.fromkeys(keyword_cfg.get("hn_terms", keyword_cfg.get("strong_terms", []))))
        people_cfg = self.config.get("people", [])
        priority_people = [p["name"] for p in people_cfg if "prior_founder" in p.get("specialty_tags", [])]
        limit = int(self.config.get("sources", {}).get("hn_watchlist_query_limit", 25))
        queries = [(term, "term") for term in terms] + [(name, "person") for name in priority_people[:limit]]
        known_people = [r["canonical_name"] for r in self.db.rows("SELECT canonical_name FROM people")] if self.db else []
        gathered: dict[str, dict] = {}

        for query, kind in queries:
            try:
                payload = self.get(
                    "https://hn.algolia.com/api/v1/search_by_date",
                    respect_robots=False,
                    params={
                        "query": query,
                        "tags": "story",
                        "numericFilters": f"created_at_i>{int(since.timestamp())}",
                        "hitsPerPage": 50,
                    },
                ).json()
                hits = payload.get("hits", [])
            except Exception as exc:
                result.errors.append(f"{query}: {exc}")
                continue
            result.rows_fetched += len(hits)
            for hit in hits:
                text = " ".join(str(hit.get(x) or "") for x in ("title", "story_title", "story_text"))
                if kind == "term" and not matched_terms(text, [query]):
                    continue
                if kind == "person" and query.casefold() not in text.casefold():
                    continue
                key = str(hit.get("objectID") or hit.get("url") or hit.get("title"))
                record = gathered.setdefault(key, {"hit": hit, "queries": set()})
                record["queries"].add(query)

        for key, record in gathered.items():
            hit = record["hit"]
            title = hit.get("title") or hit.get("story_title") or "Untitled"
            text = " ".join(str(hit.get(x) or "") for x in ("title", "story_title", "story_text"))
            observed = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
            classification = classify_public_signal(text, keyword_cfg, known_people)
            if classification.category == "suppressed":
                continue
            candidate = extract_candidate_entity(title, text) if classification.category == "spinout" else None
            people = list(classification.watchlist_people)
            signal_type = "spinout_discovery" if classification.category == "spinout" else "industry_intelligence"
            raw = hit | {
                "classification": classification.category,
                "matched_strong_terms": list(classification.strong_terms),
                "matched_contextual_terms": list(classification.contextual_terms),
                "startup_language": list(classification.startup_terms),
                "matched_watchlist_people": people,
                "candidate_entity": candidate,
                "query_matches": sorted(record["queries"]),
            }
            result.signals.append(Signal(
                source=self.name,
                signal_type=signal_type,
                entity_name=candidate,
                observed_at=observed,
                title=title,
                person_names=people,
                url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                summary=(f"HN {classification.category}; domain terms: "
                         f"{', '.join(classification.domain_terms) or 'watchlist-person context'}; "
                         f"author {hit.get('author')}; {hit.get('points') or 0} points"),
                raw=raw,
                source_key=f"hn:{key}:{candidate or classification.category}",
            ))
        return result
