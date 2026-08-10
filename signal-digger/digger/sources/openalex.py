from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import SourceResult, Target
from .base import BaseSource


def parse_work(work: dict, fallback: datetime) -> dict:
    try:
        observed = datetime.fromisoformat(str(work.get("publication_date"))).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        observed = fallback
    authors: list[str] = []
    institutions: list[str] = []
    for authorship in work.get("authorships") or []:
        name = (authorship.get("author") or {}).get("display_name")
        if name:
            authors.append(name)
        institutions.extend(
            item.get("display_name", "") for item in authorship.get("institutions") or [] if item.get("display_name")
        )
    primary = work.get("primary_location") or {}
    return {
        "id": work.get("id"),
        "title": " ".join(str(work.get("display_name") or work.get("title") or "Untitled work").split()),
        "observed": observed,
        "url": primary.get("landing_page_url") or work.get("doi") or work.get("id"),
        "authors": list(dict.fromkeys(authors)),
        "institutions": list(dict.fromkeys(institutions)),
        "citations": int(work.get("cited_by_count") or 0),
    }


class OpenAlexSource(BaseSource):
    """Scholarly works plus author and institution metadata from OpenAlex."""

    name = "openalex"
    endpoint = "https://api.openalex.org/works"

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        api_key = self.config.get("tokens", {}).get("openalex")
        if not api_key:
            result.skipped_reason = "OPENALEX_API_KEY is not configured"
            return result
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        params = {
            "api_key": api_key,
            "search": target.query,
            "filter": f"from_publication_date:{since.date().isoformat()}",
            "sort": "publication_date:desc",
            "per_page": max(1, min(100, int(self.config.get("openalex", {}).get("per_page", 50)))),
        }
        try:
            payload = self.fetch_json(self.endpoint, params=params, respect_robots=False)
        except Exception as exc:
            result.errors.append(f"works search: {exc}")
            return result
        works = payload.get("results") or []
        result.rows_fetched = len(works)
        for raw_work in works:
            work = parse_work(raw_work, self.utcnow())
            result.findings.append(self.finding(
                source=self.name,
                category="general_signal",
                title=f"Research index: {work['title']}",
                observed_at=work["observed"],
                url=work["url"],
                summary=(f"{', '.join(work['institutions'][:3])}; " if work["institutions"] else "") + f"{work['citations']} citations",
                entities=[target.query, *work["institutions"]],
                people=work["authors"],
                raw={"openalex_id": work["id"], "institutions": work["institutions"], "citations": work["citations"]},
                dedupe_key=f"openalex:{work['id'] or work['title']}",
            ))
        return result
