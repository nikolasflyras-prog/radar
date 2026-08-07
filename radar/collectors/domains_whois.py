from __future__ import annotations

import re
import socket
from datetime import datetime, timedelta, timezone

from dateutil.parser import parse as parse_date

from .base import BaseCollector
from ..models import CollectorResult, Signal


class DomainsRdapCollector(BaseCollector):
    name = "domains"

    @staticmethod
    def _registration_date(events: dict) -> datetime | None:
        value = events.get("registration")
        if not value:
            return None
        try:
            parsed = parse_date(value)
        except Exception:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        if not self.db:
            result.errors.append("Domain corroboration requires the candidate database")
            return result

        candidates = self.db.rows(
            "SELECT canonical_name FROM entities WHERE first_seen >= ? ORDER BY first_seen DESC LIMIT 100",
            ((since or self.utcnow() - timedelta(days=30)).isoformat(),),
        )
        max_age_days = int(self.config.get("domain_recent_registration_days", 730))

        for row in candidates:
            stem = re.sub(r"[^a-z0-9]", "", row["canonical_name"].casefold())
            if len(stem) < 3:
                continue
            best_signal: Signal | None = None
            best_weight = -1.0

            for suffix in (".com", ".ai", ".io"):
                domain = stem + suffix
                try:
                    socket.getaddrinfo(domain, 443)
                except OSError:
                    continue
                result.rows_fetched += 1
                try:
                    rdap = self.get(f"https://rdap.org/domain/{domain}", respect_robots=False).json()
                    events = {e.get("eventAction"): e.get("eventDate") for e in rdap.get("events", [])}
                    registered = self._registration_date(events)
                    if registered is None:
                        continue
                    age_days = max(0, (self.utcnow() - registered).days)
                    # An old domain is evidence of an established company, not a fresh spinout.
                    # Skip it rather than allowing ordinary careers text to inflate the score.
                    if age_days > max_age_days:
                        continue
                    page = self.get(f"https://{domain}").text[:200000]
                except Exception as exc:
                    result.errors.append(f"{domain}: {exc}")
                    continue

                hiring = any(x in page.casefold() for x in (
                    "hiring", "careers", "stealth", "founding engineer", "silicon engineer",
                ))
                signal_type = "domain_hiring" if hiring else "domain_registered"
                weight = 15.0 if hiring else 5.0
                signal = Signal(
                    source=self.name,
                    signal_type=signal_type,
                    entity_name=row["canonical_name"],
                    observed_at=self.utcnow(),
                    title=f"Recent domain corroboration: {domain}",
                    url=f"https://{domain}",
                    summary=(
                        f"Recent domain resolves; registration: {registered.date().isoformat()}; "
                        f"age: {age_days} days; hiring language: {hiring}"
                    ),
                    raw={
                        "domain": domain, "events": events, "hiring": hiring,
                        "registration_age_days": age_days,
                    },
                    base_weight=weight,
                    source_key=f"rdap:{domain}:{events.get('registration')}",
                )
                if weight > best_weight:
                    best_signal, best_weight = signal, weight

            # At most one domain signal per entity per run. Multiple suffixes are corroboration,
            # not independent evidence and should not stack into a false Watching score.
            if best_signal is not None:
                result.signals.append(best_signal)

        return result
