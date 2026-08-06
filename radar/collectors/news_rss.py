from __future__ import annotations

from datetime import datetime, timedelta, timezone

import feedparser
from dateutil.parser import parse as parse_date

from .base import BaseCollector
from ..models import CollectorResult, Signal
from ..relevance import classify_public_signal, extract_candidate_entity


class NewsRSSCollector(BaseCollector):
    name = "rss"

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("rss", 14)))
        keyword_cfg = self.config["keywords"]
        known_people = [r["canonical_name"] for r in self.db.rows("SELECT canonical_name FROM people")] if self.db else []
        for feed in self.config.get("feeds", []):
            try:
                parsed = feedparser.parse(self.get(feed["url"]).content)
                if parsed.bozo and not parsed.entries:
                    raise ValueError(str(parsed.bozo_exception))
            except Exception as exc:
                result.errors.append(f"{feed.get('name')}: {exc}")
                continue
            result.rows_fetched += len(parsed.entries)
            for entry in parsed.entries:
                title = entry.get("title", "Untitled")
                blob = f"{title} {entry.get('summary', '')}"
                classification = classify_public_signal(blob, keyword_cfg, known_people)
                if classification.category == "suppressed":
                    continue
                try:
                    observed = parse_date(entry.get("published") or entry.get("updated"))
                except Exception:
                    observed = self.utcnow()
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                if observed < since:
                    continue
                candidate = extract_candidate_entity(title, blob) if classification.category == "spinout" else None
                people = list(classification.watchlist_people)
                signal_type = "spinout_discovery" if classification.category == "spinout" else "industry_intelligence"
                raw = dict(entry) | {
                    "classification": classification.category,
                    "matched_strong_terms": list(classification.strong_terms),
                    "matched_contextual_terms": list(classification.contextual_terms),
                    "startup_language": list(classification.startup_terms),
                    "matched_watchlist_people": people,
                    "candidate_entity": candidate,
                    "feed_name": feed.get("name"),
                }
                result.signals.append(Signal(
                    source=self.name,
                    signal_type=signal_type,
                    entity_name=candidate,
                    person_names=people,
                    title=title,
                    observed_at=observed,
                    url=entry.get("link"),
                    summary=(f"{feed.get('name')}: {classification.category}; domain terms: "
                             f"{', '.join(classification.domain_terms)}"),
                    raw=raw,
                    source_key=f"rss:{entry.get('id') or entry.get('link')}:{candidate or classification.category}",
                ))
        return result
