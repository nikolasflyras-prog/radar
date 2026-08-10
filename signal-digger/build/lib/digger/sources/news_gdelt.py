from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from dateutil.parser import parse as parse_date

from ..models import SourceResult, Target
from ..textutil import MA_KEYWORDS, classify_ma_or_general
from .base import BaseSource


GDELT_MAX_LOOKBACK_DAYS = 90
GDELT_MAX_RECORDS = 250


def _quote_phrase(value: str) -> str:
    """Return a GDELT exact-phrase token, stripping characters that could break
    the query grammar. GDELT requires whitespace-containing phrases inside
    quotes and does not support escaping a quote inside an exact phrase."""
    cleaned = " ".join((value or "").replace('"', " ").split())
    return f'"{cleaned}"'


def build_queries(target: Target) -> tuple[str, str]:
    """Build the focused M&A query and broad target query using valid GDELT DOC
    2.0 syntax. Every M&A term is quoted so multiword terms such as
    ``definitive agreement`` cannot invalidate the entire OR block."""
    target_phrase = _quote_phrase(target.query)
    ma_terms = " OR ".join(_quote_phrase(term) for term in MA_KEYWORDS[:8])
    return f"{target_phrase} ({ma_terms})", target_phrase


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
            "maxrecords": min(GDELT_MAX_RECORDS, max(1, max_records)),
            "sort": "HybridRel",
            # DOC 2.0's searchable corpus is a rolling three-month window.
            "timespan": f"{min(GDELT_MAX_LOOKBACK_DAYS, max(1, timespan_days))}d",
        }
        text = self.fetch_text(self.endpoint, params=params, respect_robots=False)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            # GDELT sometimes returns a plain-text query/rate-limit error with a
            # successful HTTP status. Preserve a useful, bounded explanation in
            # Source Run Health instead of exposing only "JSONDecodeError".
            detail = " ".join(text.split())[:240] or "empty response"
            raise ValueError(f"GDELT returned non-JSON response: {detail}") from exc
        return payload.get("articles", []) if isinstance(payload, dict) else []

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        queries = build_queries(target)
        seen: dict[str, dict] = {}
        for query in queries:
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
