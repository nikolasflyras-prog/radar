from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Category = Literal["ma_deal", "people_movement", "general_signal"]
Mode = Literal["company", "sector", "person"]


@dataclass(slots=True)
class Target:
    """The thing a run is pointed at."""

    mode: Mode
    query: str

    @property
    def label(self) -> str:
        return self.query


@dataclass(slots=True)
class Finding:
    source: str
    category: Category
    title: str
    observed_at: datetime
    url: str | None = None
    summary: str = ""
    entities: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str | None = None
    quiet: bool = False
    quiet_reason: str = ""

    def iso_time(self) -> str:
        value = self.observed_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    def key(self) -> str:
        return self.dedupe_key or "|".join([self.source, self.title, self.url or "", self.iso_time()[:10]])


@dataclass(slots=True)
class SourceResult:
    source: str
    findings: list[Finding] = field(default_factory=list)
    rows_fetched: int = 0
    errors: list[str] = field(default_factory=list)
    cached: bool = False
    skipped_reason: str = ""

    @property
    def status(self) -> str:
        if self.skipped_reason:
            return "skipped"
        if self.errors and not self.findings and not self.rows_fetched:
            return "failed"
        if self.errors:
            return "partial"
        return "ok"
