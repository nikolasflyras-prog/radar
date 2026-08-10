from __future__ import annotations

from datetime import timedelta, timezone

import feedparser
from dateutil.parser import parse as parse_date

from ..models import SourceResult, Target
from .base import BaseSource


def parse_entry(entry: dict, fallback) -> dict:
    published_raw = entry.get("published") or entry.get("updated") or ""
    try:
        observed = parse_date(published_raw)
        observed = observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        observed = fallback
    authors = [author.get("name", "") for author in entry.get("authors", []) if author.get("name")]
    return {
        "id": entry.get("id") or entry.get("link"),
        "title": " ".join(str(entry.get("title") or "Untitled paper").split()),
        "summary": " ".join(str(entry.get("summary") or "").split()),
        "observed": observed,
        "authors": authors,
    }


class ArxivSource(BaseSource):
    """Recent technical preprints matching a company, sector, or researcher."""

    name = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        max_results = max(1, min(100, int(self.config.get("arxiv", {}).get("max_results", 40))))
        params = {
            "search_query": f'all:"{target.query.replace(chr(34), " ")}"',
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        try:
            text = self.fetch_text(self.endpoint, params=params, respect_robots=False)
        except Exception as exc:
            result.errors.append(f"paper search: {exc}")
            return result
        feed = feedparser.parse(text)
        if getattr(feed, "bozo", False) and not feed.entries:
            result.errors.append(f"paper feed parse: {feed.bozo_exception}")
            return result
        result.rows_fetched = len(feed.entries)
        for raw_entry in feed.entries:
            entry = parse_entry(raw_entry, self.utcnow())
            if entry["observed"] < since:
                continue
            result.findings.append(self.finding(
                source=self.name,
                category="general_signal",
                title=f"Research paper: {entry['title']}",
                observed_at=entry["observed"],
                url=entry["id"],
                summary=(f"{', '.join(entry['authors'][:4])}. " if entry["authors"] else "") + entry["summary"][:420],
                entities=[target.query],
                people=entry["authors"],
                raw={"authors": entry["authors"], "paper_id": entry["id"]},
                dedupe_key=f"arxiv:{entry['id'] or entry['title']}",
            ))
        return result
