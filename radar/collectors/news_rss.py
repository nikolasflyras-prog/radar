from __future__ import annotations

from datetime import datetime, timedelta, timezone

import feedparser
from dateutil.parser import parse as parse_date

from .base import BaseCollector
from ..models import CollectorResult, Signal
from ..relevance import classify_public_signal, extract_candidate_entity, matched_employers, has_departure_context, watchlist_identity_matches


class NewsRSSCollector(BaseCollector):
    name = "rss"

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("rss", 14)))
        keyword_cfg = self.config.get("keywords", {})
        people_cfg = self.config.get("people", [])
        watched_names = [p.get("name", "") for p in people_cfg]
        employers = list(dict.fromkeys(p.get("last_known_employer") for p in people_cfg if p.get("last_known_employer")))

        for feed in self.config.get("feeds", []):
            try:
                response = self.get(feed["url"], respect_robots=feed.get("respect_robots", True))
                parsed = feedparser.parse(response.content)
                if parsed.bozo and not parsed.entries:
                    raise ValueError(str(parsed.bozo_exception))
            except Exception as exc:
                result.errors.append(f"{feed.get('name')}: {exc}")
                continue
            result.rows_fetched += len(parsed.entries)

            for entry in parsed.entries:
                title = " ".join(str(entry.get("title") or "Untitled").split())
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
                candidate = extract_candidate_entity(title, blob)
                promoted_spinout = classification.category == "industry" and departure_context
                if people and (classification.category == "spinout" or promoted_spinout):
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
                    "candidate_entity": candidate,
                    "matched_strong_terms": list(classification.strong_terms),
                    "matched_contextual_terms": list(classification.contextual_terms),
                    "startup_language": list(classification.startup_terms),
                    "matched_watchlist_people": people,
                    "matched_watchlist_employers": employer_hits,
                    "departure_context": departure_context,
                    "feed_name": feed.get("name"),
                })
                result.signals.append(Signal(
                    source=self.name,
                    signal_type=signal_type,
                    entity_name=candidate,
                    person_names=people,
                    title=title,
                    observed_at=observed,
                    url=entry.get("link"),
                    summary=f"{feed.get('name')}: {category}; employer matches: {', '.join(employer_hits) or 'none'}",
                    raw=raw,
                    base_weight=weight,
                    source_key=f"rss:{entry.get('id') or entry.get('link')}",
                ))
        return result
