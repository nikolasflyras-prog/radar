from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from ..models import Mode, SourceResult, Target
from .base import BaseSource

FOUNDING_ROLE_RE = re.compile(r"\bfounding\b", re.IGNORECASE)


def is_founding_role(title: str) -> bool:
    return bool(FOUNDING_ROLE_RE.search(title or ""))


def detect_surge(previous_count: int | None, current_count: int, threshold: int) -> bool:
    """A hiring surge is a jump in open-posting count between runs, not an absolute
    level — so a first-ever run (no previous_count) never counts as a surge."""
    if previous_count is None:
        return False
    return (current_count - previous_count) >= threshold


def slugs_for(config: dict, target: Target) -> dict[str, list[str]]:
    overrides = config.get("job_boards", {}).get("slug_overrides", {})
    match = overrides.get(target.query)
    if match:
        return {"greenhouse": list(match.get("greenhouse", [])), "lever": list(match.get("lever", []))}
    guess = re.sub(r"[^a-z0-9]", "", target.query.casefold())
    return {"greenhouse": [guess] if guess else [], "lever": [guess] if guess else []}


class JobBoardsSource(BaseSource):
    """Greenhouse and Lever public job-board APIs: current open postings, flagging
    "Founding [Role]" listings (an early/quiet signal on their own) and hiring
    surges versus the previous cached run. Company/sector targets only — boards
    are per-employer, not per-person."""

    name = "job_boards"
    modes: tuple[Mode, ...] = ("company", "sector")

    def _surge_key(self, board: str, slug: str) -> str:
        return f"surge-count:{board}:{slug}"

    def _record_and_check_surge(self, board: str, slug: str, current_count: int) -> tuple[int | None, bool]:
        threshold = int(self.config.get("job_boards", {}).get("surge_threshold", 3))
        key = self._surge_key(board, slug)
        previous = None
        if self.use_cache:
            raw = self.cache.get(self.name, key, ttl_seconds=float("inf"))
            if raw:
                previous = json.loads(raw).get("count")
            self.cache.set(self.name, key, json.dumps({"count": current_count, "at": self.utcnow().isoformat()}))
        return previous, detect_surge(previous, current_count, threshold)

    def _greenhouse(self, result: SourceResult, slug: str) -> None:
        try:
            payload = self.fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", respect_robots=False)
        except Exception as exc:
            result.errors.append(f"greenhouse/{slug}: {exc}")
            return
        jobs = payload.get("jobs") or []
        result.rows_fetched += len(jobs)
        previous, surged = self._record_and_check_surge("greenhouse", slug, len(jobs))
        if surged:
            result.findings.append(self.finding(
                source=self.name, category="people_movement",
                title=f"Hiring surge on Greenhouse board {slug}",
                observed_at=self.utcnow(), url=f"https://boards.greenhouse.io/{slug}",
                summary=f"Open postings went from {previous} to {len(jobs)} since the last run",
                entities=[slug], raw={"previous": previous, "current": len(jobs)},
                quiet=True, quiet_reason="Hiring surge with no accompanying announcement found",
                dedupe_key=f"surge:greenhouse:{slug}:{self.utcnow():%Y-%m-%d}",
            ))
        for job in jobs:
            title = job.get("title") or "Untitled role"
            founding = is_founding_role(title)
            try:
                observed = datetime.fromisoformat(str(job.get("updated_at")).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                observed = self.utcnow()
            result.findings.append(self.finding(
                source=self.name, category="people_movement",
                title=f"Greenhouse posting: {title}",
                observed_at=observed, url=job.get("absolute_url"),
                summary=f"{(job.get('location') or {}).get('name', 'location unspecified')}",
                entities=[slug], raw={"id": job.get("id"), "title": title},
                quiet=founding, quiet_reason='"Founding" role posting worth tracing to a name' if founding else "",
                dedupe_key=f"gh-job:{job.get('id')}",
            ))

    def _lever(self, result: SourceResult, slug: str) -> None:
        try:
            postings = self.fetch_json(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, respect_robots=False)
        except Exception as exc:
            result.errors.append(f"lever/{slug}: {exc}")
            return
        if not isinstance(postings, list):
            result.errors.append(f"lever/{slug}: unexpected response shape")
            return
        result.rows_fetched += len(postings)
        previous, surged = self._record_and_check_surge("lever", slug, len(postings))
        if surged:
            result.findings.append(self.finding(
                source=self.name, category="people_movement",
                title=f"Hiring surge on Lever board {slug}",
                observed_at=self.utcnow(), url=f"https://jobs.lever.co/{slug}",
                summary=f"Open postings went from {previous} to {len(postings)} since the last run",
                entities=[slug], raw={"previous": previous, "current": len(postings)},
                quiet=True, quiet_reason="Hiring surge with no accompanying announcement found",
                dedupe_key=f"surge:lever:{slug}:{self.utcnow():%Y-%m-%d}",
            ))
        for posting in postings:
            title = posting.get("text") or "Untitled role"
            founding = is_founding_role(title)
            created = posting.get("createdAt")
            observed = datetime.fromtimestamp(created / 1000, tz=timezone.utc) if created else self.utcnow()
            location = ((posting.get("categories") or {}).get("location")) or "location unspecified"
            result.findings.append(self.finding(
                source=self.name, category="people_movement",
                title=f"Lever posting: {title}",
                observed_at=observed, url=posting.get("hostedUrl"),
                summary=location, entities=[slug], raw={"id": posting.get("id"), "title": title},
                quiet=founding, quiet_reason='"Founding" role posting worth tracing to a name' if founding else "",
                dedupe_key=f"lever-job:{posting.get('id')}",
            ))

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        slugs = slugs_for(self.config, target)
        if not slugs["greenhouse"] and not slugs["lever"]:
            result.skipped_reason = "no job-board slug configured or derivable for this target"
            return result
        for slug in slugs["greenhouse"]:
            self._greenhouse(result, slug)
        for slug in slugs["lever"]:
            self._lever(result, slug)
        return result
