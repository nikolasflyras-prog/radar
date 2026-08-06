from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from .base import BaseCollector
from ..models import CollectorResult, Signal


class HNAlgoliaCollector(BaseCollector):
    name = "hn"

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("hn", 14)))
        terms = self.config["keywords"].get("hn_terms", self.config["keywords"].get("terms", [])[:12])
        queries = list(dict.fromkeys(terms + [p["name"] for p in self.config.get("people", [])]))
        known_entities = self.db.rows("SELECT canonical_name FROM entities") if self.db else []
        known_people = self.db.rows("SELECT canonical_name FROM people") if self.db else []
        for query in queries[:50]:
            url = f"https://hn.algolia.com/api/v1/search_by_date?query={quote(query)}&numericFilters=created_at_i>{int(since.timestamp())}&hitsPerPage=100"
            try: hits = self.get(url, respect_robots=False).json().get("hits", [])
            except Exception as exc: result.errors.append(f"{query}: {exc}"); continue
            result.rows_fetched += len(hits)
            for hit in hits:
                text = " ".join(str(hit.get(x) or "") for x in ("title", "story_title", "comment_text"))
                if query.casefold() not in text.casefold(): continue
                stealth = any(x in text.casefold() for x in ("stealth", "has left", "departed", "founder", "show hn"))
                observed = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
                people = [x["canonical_name"] for x in known_people if x["canonical_name"].casefold() in text.casefold()]
                entities = [x["canonical_name"] for x in known_entities if x["canonical_name"].casefold() in text.casefold()] or [None]
                for entity in entities:
                    result.signals.append(Signal(source=self.name, signal_type="news_departure_stealth" if stealth else "hn_keyword",
                        entity_name=entity, observed_at=observed, title=(hit.get("title") or hit.get("story_title") or text[:100]),
                        person_names=people, url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                        summary=f"HN match for '{query}' by {hit.get('author')}; {hit.get('points') or 0} points",
                        raw=hit, source_key=f"hn:{hit.get('objectID')}:{query}:{entity or 'unresolved'}"))
        return result
