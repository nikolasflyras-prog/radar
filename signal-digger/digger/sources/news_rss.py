from __future__ import annotations

from datetime import timedelta, timezone
from urllib.parse import quote

import feedparser
from dateutil.parser import parse as parse_date

from ..models import SourceResult, Target
from ..textutil import classify_ma_or_general, mentions_target
from .base import BaseSource


def target_feeds(configured: list[dict], query: str) -> list[dict]:
    """Configured feeds plus a Google News RSS search for the target itself, so the
    source is useful with zero configuration. Pure function for tests."""
    feeds = list(configured)
    feeds.append({
        "name": "Google News", "url": f"https://news.google.com/rss/search?q={quote(query)}",
        "respect_robots": False, "requires_mention_check": False,
    })
    return feeds


class NewsRssSource(BaseSource):
    """RSS feed search: any feeds configured under `rss_feeds`, plus a Google News
    RSS query for the target. Each entry is bucketed ma_deal or general_signal by
    the same keyword check as the GDELT source."""

    name = "news_rss"

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        for feed in target_feeds(self.config.get("rss_feeds", []), target.query):
            try:
                text = self.fetch_text(feed["url"], respect_robots=feed.get("respect_robots", True))
                parsed = feedparser.parse(text)
                if parsed.bozo and not parsed.entries:
                    raise ValueError(str(parsed.bozo_exception))
            except Exception as exc:
                result.errors.append(f"{feed.get('name')}: {exc}")
                continue
            result.rows_fetched += len(parsed.entries)
            for entry in parsed.entries:
                title = " ".join(str(entry.get("title") or "Untitled").split())
                blob = f"{title} {entry.get('summary', '')}"
                if feed.get("requires_mention_check", True) and not mentions_target(blob, target.query):
                    continue
                try:
                    observed = parse_date(entry.get("published") or entry.get("updated"))
                    observed = observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed.astimezone(timezone.utc)
                except (ValueError, TypeError, OverflowError):
                    observed = self.utcnow()
                if observed < since:
                    continue
                category, hits = classify_ma_or_general(blob)
                result.findings.append(self.finding(
                    source=self.name, category=category, title=title, observed_at=observed, url=entry.get("link"),
                    summary=f"{feed.get('name')}" + (f"; matched: {', '.join(hits)}" if hits else ""),
                    entities=[target.query],
                    raw={"feed": feed.get("name"), "matched_ma_terms": hits},
                    dedupe_key=f"rss:{entry.get('id') or entry.get('link')}",
                ))
        return result
