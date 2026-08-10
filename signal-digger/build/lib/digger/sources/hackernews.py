from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from ..models import SourceResult, Target
from .base import BaseSource

HIRING_TITLE_MARKERS = ("who is hiring", "who's hiring", "freelancer? seeking freelancer")


def classify_hit(hit: dict, kind: str) -> tuple[str, str]:
    """Return (signal_type, title) for one HN Algolia hit. Pure function for tests."""
    story_title = (hit.get("title") or hit.get("story_title") or "").strip()
    if kind == "story":
        return "story_mention", story_title or "Untitled story"
    lowered = story_title.casefold()
    if any(marker in lowered for marker in HIRING_TITLE_MARKERS):
        return "hiring_thread_comment", f"Comment on \"{story_title}\""
    return "comment_mention", f"Comment on \"{story_title or 'a story'}\""


class HackerNewsSource(BaseSource):
    """Hacker News mentions via the Algolia search API: stories about the target,
    "Who's hiring" thread comments naming it, and other comments self-identifying
    with it. Applies to all three run modes."""

    name = "hackernews"
    endpoint = "https://hn.algolia.com/api/v1/search_by_date"

    def _search(self, query: str, tags: str, since: datetime) -> list[dict]:
        url = f"{self.endpoint}?query={quote(query)}&tags={tags}&numericFilters=created_at_i>{int(since.timestamp())}&hitsPerPage=100"
        payload = self.fetch_json(url, respect_robots=False)
        return payload.get("hits", [])

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        for kind, tags in (("story", "story"), ("comment", "comment")):
            try:
                hits = self._search(target.query, tags, since)
            except Exception as exc:
                result.errors.append(f"{kind} search: {exc}")
                continue
            result.rows_fetched += len(hits)
            for hit in hits:
                signal_type, title = classify_hit(hit, kind)
                observed = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc) if hit.get("created_at_i") else self.utcnow()
                object_id = hit.get("objectID")
                url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
                result.findings.append(self.finding(
                    source=self.name, category="people_movement",
                    title=title, observed_at=observed, url=url,
                    summary=f"{signal_type.replace('_', ' ')} by {hit.get('author') or 'unknown'}; {hit.get('points') or 0} points",
                    entities=[target.query],
                    raw={"kind": kind, "signal_type": signal_type, "author": hit.get("author"), "points": hit.get("points")},
                    quiet=signal_type == "hiring_thread_comment",
                    quiet_reason="Hiring-thread self-identification with no public announcement" if signal_type == "hiring_thread_comment" else "",
                    dedupe_key=f"hn:{object_id}",
                ))
        return result
