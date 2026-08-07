from __future__ import annotations

from datetime import timedelta, timezone

from dateutil.parser import parse as parse_date

from ..models import Mode, SourceResult, Target
from ..textutil import mentions_target
from .base import BaseSource


def _names(value) -> list[str]:
    if not value:
        return []
    return [x.get("name", "") if isinstance(x, dict) else str(x) for x in value]


def parse_assignment_doc(doc: dict, query: str) -> dict | None:
    """Normalize one USPTO assignment-API document; return None if neither side of
    the transfer names the target. Pure function for fixture-based unit testing."""
    assignors = _names(doc.get("assignors") or doc.get("assignorNames"))
    assignees = _names(doc.get("assignees") or doc.get("assigneeNames"))
    assignor_text, assignee_text = ", ".join(assignors), ", ".join(assignees)
    if not (mentions_target(assignor_text, query) or mentions_target(assignee_text, query)):
        return None
    return {
        "assignors": assignors,
        "assignees": assignees,
        "recorded_date": doc.get("recordedDate") or doc.get("recorded_date") or "",
        "reel_frame": str(doc.get("reelFrame") or doc.get("id") or f"{assignor_text}:{assignee_text}"),
        "url": doc.get("assignmentUrl"),
        "correspondent": doc.get("correspondentName"),
    }


class UsptoAssignmentsSource(BaseSource):
    """USPTO patent assignment records — bulk transfers of patents to or from the
    target. A transfer with no matching news is often the quietest kind of signal.
    Company/sector targets only."""

    name = "uspto_assignments"
    modes: tuple[Mode, ...] = ("company", "sector")
    endpoint = "https://assignment-api.uspto.gov/patent/basicSearch"

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        params = {"query": target.query, "startDate": since.date().isoformat(), "rows": 100}
        try:
            payload = self.fetch_json(self.endpoint, params=params, respect_robots=False)
        except Exception as exc:
            result.errors.append(f"assignment search: {exc}")
            return result
        docs = payload.get("docs") or payload.get("results") or payload.get("patentAssignments") or []
        result.rows_fetched = len(docs)
        for doc in docs:
            parsed = parse_assignment_doc(doc, target.query)
            if not parsed:
                continue
            try:
                observed = parse_date(parsed["recorded_date"])
                observed = observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed.astimezone(timezone.utc)
            except (ValueError, OverflowError, TypeError):
                observed = self.utcnow()
            assignor, assignee = ", ".join(parsed["assignors"]), ", ".join(parsed["assignees"])
            result.findings.append(self.finding(
                source=self.name, category="ma_deal",
                title=f"Patent assignment: {assignor} → {assignee}",
                observed_at=observed, url=parsed["url"],
                summary=f"Recorded {parsed['recorded_date'] or 'unknown date'}; correspondent: {parsed['correspondent'] or 'unknown'}",
                entities=[e for e in (assignor, assignee) if e],
                raw=parsed,
                dedupe_key=f"uspto:{parsed['reel_frame']}",
            ))
        return result
