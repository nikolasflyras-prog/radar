from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class Signal:
    source: str
    signal_type: str
    title: str
    observed_at: datetime
    entity_name: str | None = None
    person_names: list[str] = field(default_factory=list)
    url: str | None = None
    summary: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    source_key: str | None = None
    base_weight: float | None = None
    manually_entered: bool = False

    def iso_time(self) -> str:
        value = self.observed_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


@dataclass(slots=True)
class CollectorResult:
    source: str
    signals: list[Signal] = field(default_factory=list)
    rows_fetched: int = 0
    errors: list[str] = field(default_factory=list)

