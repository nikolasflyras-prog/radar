from __future__ import annotations

from datetime import timedelta, timezone

from dateutil.parser import parse as parse_date

from ..models import Mode, SourceResult, Target
from ..textutil import mentions_target
from .base import BaseSource


def _names(value) -> list[str]:
    if not value:
        return []
    keys = ("name", "assignorName", "assigneeName", "organizationName", "entityName")
    names: list[str] = []
    for item in value:
        if isinstance(item, dict):
            names.append(next((str(item[key]) for key in keys if item.get(key)), ""))
        else:
            names.append(str(item))
    return [name for name in names if name]


def parse_assignment_doc(doc: dict, query: str) -> dict | None:
    """Normalize one USPTO assignment-API document; return None if neither side of
    the transfer names the target. Pure function for fixture-based unit testing."""
    assignors = _names(doc.get("assignors") or doc.get("assignorNames") or doc.get("assignorBag"))
    assignees = _names(doc.get("assignees") or doc.get("assigneeNames") or doc.get("assigneeBag"))
    assignor_text, assignee_text = ", ".join(assignors), ", ".join(assignees)
    if not (mentions_target(assignor_text, query) or mentions_target(assignee_text, query)):
        return None
    return {
        "assignors": assignors,
        "assignees": assignees,
        "recorded_date": doc.get("recordedDate") or doc.get("recorded_date") or doc.get("assignmentReceivedDate") or "",
        "reel_frame": str(doc.get("reelFrame") or doc.get("reelAndFrameNumber") or doc.get("id") or f"{assignor_text}:{assignee_text}"),
        "url": doc.get("assignmentUrl") or doc.get("documentUrl"),
        "correspondent": doc.get("correspondentName") or doc.get("correspondentAddress"),
    }


def application_rows(payload: dict) -> list[dict]:
    return list(
        payload.get("patentFileWrapperDataBag")
        or payload.get("results")
        or payload.get("docs")
        or []
    )


def application_number(row: dict) -> str:
    metadata = row.get("applicationMetaData") or row.get("applicationMetadata") or {}
    identification = metadata.get("applicationIdentification") or {}
    return str(
        row.get("applicationNumberText")
        or metadata.get("applicationNumberText")
        or identification.get("applicationNumberText")
        or ""
    ).replace("/", "").replace(",", "").strip()


def assignment_rows(payload: dict) -> list[dict]:
    return list(
        payload.get("assignmentBag")
        or payload.get("patentAssignmentDataBag")
        or payload.get("assignments")
        or payload.get("results")
        or []
    )


class UsptoAssignmentsSource(BaseSource):
    """USPTO patent assignment records — bulk transfers of patents to or from the
    target. A transfer with no matching news is often the quietest kind of signal.
    Company/sector targets only."""

    name = "uspto_assignments"
    modes: tuple[Mode, ...] = ("company", "sector")
    search_endpoint = "https://api.uspto.gov/api/v1/patent/applications/search"
    assignment_endpoint = "https://api.uspto.gov/api/v1/patent/applications/{application_number}/assignments"

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        api_key = self.config.get("tokens", {}).get("uspto")
        if not api_key:
            result.skipped_reason = "USPTO_API_KEY is not configured for the current Open Data Portal API"
            return result
        self.session.headers.update({"X-API-KEY": str(api_key)})
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        max_apps = max(1, min(100, int(self.config.get("uspto", {}).get("max_applications", 25))))
        params = {"q": f'"{target.query}"', "offset": 0, "limit": max_apps}
        try:
            payload = self.fetch_json(self.search_endpoint, params=params, respect_robots=False)
        except Exception as exc:
            result.errors.append(f"application search: {exc}")
            return result
        docs: list[dict] = []
        for application in application_rows(payload):
            number = application_number(application)
            if not number:
                continue
            embedded = assignment_rows(application)
            if embedded:
                for assignment in embedded:
                    assignment.setdefault("applicationNumberText", number)
                    docs.append(assignment)
                continue
            try:
                assignment_payload = self.fetch_json(
                    self.assignment_endpoint.format(application_number=number),
                    respect_robots=False,
                )
            except Exception as exc:
                result.errors.append(f"assignments for {number}: {exc}")
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in {401, 403}:
                    result.errors.append(
                        "USPTO assignment detail access was denied; skipped remaining detail requests"
                    )
                    break
                continue
            for assignment in assignment_rows(assignment_payload):
                assignment.setdefault("applicationNumberText", number)
                docs.append(assignment)
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
            if observed < since:
                continue
            assignor, assignee = ", ".join(parsed["assignors"]), ", ".join(parsed["assignees"])
            result.findings.append(self.finding(
                source=self.name, category="ma_deal",
                title=f"Patent assignment: {assignor} → {assignee}",
                observed_at=observed, url=parsed["url"] or "https://assignmentcenter.uspto.gov/",
                summary=f"Recorded {parsed['recorded_date'] or 'unknown date'}; correspondent: {parsed['correspondent'] or 'unknown'}",
                entities=[e for e in (assignor, assignee) if e],
                raw={**parsed, "application_number": doc.get("applicationNumberText")},
                dedupe_key=f"uspto:{parsed['reel_frame']}",
            ))
        return result
