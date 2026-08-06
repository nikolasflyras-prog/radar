from __future__ import annotations

from datetime import datetime, timedelta, timezone
import feedparser
from dateutil.parser import parse as parse_date
from .base import BaseCollector
from ..models import CollectorResult, Signal


class NewsRSSCollector(BaseCollector):
    name = "rss"
    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("rss", 14)))
        keywords = [k.casefold() for k in self.config["keywords"].get("terms", [])]
        language = self.config["keywords"].get("departure_language", [])
        known_entities = self.db.rows("SELECT canonical_name FROM entities") if self.db else []
        known_people = self.db.rows("SELECT canonical_name FROM people") if self.db else []
        for feed in self.config.get("feeds", []):
            try:
                parsed = feedparser.parse(self.get(feed["url"]).content)
                if parsed.bozo and not parsed.entries: raise ValueError(str(parsed.bozo_exception))
            except Exception as exc: result.errors.append(f"{feed.get('name')}: {exc}"); continue
            result.rows_fetched += len(parsed.entries)
            for entry in parsed.entries:
                blob = f"{entry.get('title','')} {entry.get('summary','')}"
                matches = [k for k in keywords if k in blob.casefold()]
                if not matches: continue
                try: observed = parse_date(entry.get("published") or entry.get("updated"))
                except Exception: observed = self.utcnow()
                if observed.tzinfo is None: observed = observed.replace(tzinfo=timezone.utc)
                if observed < since: continue
                strong = any(x.casefold() in blob.casefold() for x in language)
                people = [x["canonical_name"] for x in known_people if x["canonical_name"].casefold() in blob.casefold()]
                entities = [x["canonical_name"] for x in known_entities if x["canonical_name"].casefold() in blob.casefold()] or [None]
                for entity in entities:
                    result.signals.append(Signal(source=self.name, signal_type="news_departure_stealth" if strong else "news_keyword",
                        entity_name=entity, person_names=people, title=entry.get("title", "Untitled"), observed_at=observed, url=entry.get("link"),
                        summary=f"{feed.get('name')}: matched {', '.join(matches[:5])}", raw=dict(entry),
                        source_key=f"rss:{entry.get('id') or entry.get('link')}:{entity or 'unresolved'}"))
        return result
