from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from dateutil.parser import parse as parse_date

from ..models import SourceResult, Target
from ..textutil import MA_KEYWORDS, classify_ma_or_general
from .base import BaseSource


def parse_observed(seendate: str | None, fallback: datetime) -> datetime:
    if not seendate:
        return fallback
    try:
        parsed = parse_date(seendate)
    except (ValueError, OverflowError):
        return fallback
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


class NewsGdeltSource(BaseSource):
    """GDELT DOC 2.0 news search. Runs one query for M&A-flavored language and one
    broad recency query for the target, then buckets every article by whether it
    actually contains deal language — so the same client covers both the
    acquisition/merger search and the general "anything recent" search."""

    name = "news_gdelt"
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def _search(self, query: str, timespan_days: int, max_records: int) -> list[dict]:
        params = {
            "query": query, "mode": "ArtList", "format": "json",
            "maxrecords": max_records, "sort": "HybridRel", "timespan": f"{max(1, timespan_days)}d",
        }
        payload = self.fetch_json(self.endpoint, params=params, respect_robots=False)
        return payload.get("articles", []) if isinstance(payload, dict) else []

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        ma_terms = " OR ".join(MA_KEYWORDS[:8])
        queries = {
            "ma_deal": f'"{target.query}" ({ma_terms})',
            "general_signal": f'"{target.query}"',
        }
        seen: dict[str, dict] = {}
        for query in queries.values():
            try:
                articles = self._search(query, lookback, int(self.config.get("news_search", {}).get("records_per_query", 75)))
            except Exception as exc:
                result.errors.append(f"{query}: {exc}")
                continue
            result.rows_fetched += len(articles)
            for article in articles:
                key = article.get("url") or article.get("title")
                if key:
                    seen[key] = article
        for article in seen.values():
            title = " ".join(str(article.get("title") or "Untitled").split())
            url = article.get("url")
            domain = article.get("domain") or (urlparse(url).netloc if url else "")
            observed = parse_observed(article.get("seendate"), self.utcnow())
            if observed < since:
                continue
            category, hits = classify_ma_or_general(f"{title} {article.get('snippet') or ''}")
            result.findings.append(self.finding(
                source=self.name, category=category, title=title, observed_at=observed, url=url,
                summary=f"GDELT news via {domain or 'unknown publisher'}" + (f"; matched: {', '.join(hits)}" if hits else ""),
                entities=[target.query],
                raw={"domain": domain, "matched_ma_terms": hits},
                dedupe_key=f"gdelt:{url or title}",
            ))
        return result
