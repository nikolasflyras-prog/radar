from __future__ import annotations

import re
import socket
from datetime import datetime, timezone

from dateutil.parser import parse as parse_date

from ..models import SourceResult, Target
from .base import BaseSource

DEFAULT_SUFFIXES = (".com", ".ai", ".io", ".co")


def domain_candidates(query: str, suffixes: tuple[str, ...] = DEFAULT_SUFFIXES) -> list[str]:
    stem = re.sub(r"[^a-z0-9]", "", query.casefold())
    return [stem + suffix for suffix in suffixes] if len(stem) >= 3 else []


def rdap_event_date(events: list[dict], action: str) -> datetime | None:
    """Pull a named event's date out of an RDAP events list. Pure function so RDAP
    JSON fixtures can be tested without a network call."""
    for event in events:
        if event.get("eventAction") == action:
            try:
                parsed = parse_date(event.get("eventDate"))
            except (ValueError, TypeError, OverflowError):
                return None
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    return None


class DomainWhoisSource(BaseSource):
    """RDAP (WHOIS successor) lookups on domains guessed from the target name.
    Flags recent registrations and recent registrant/registrar changes — these
    almost never come with a press release, which is exactly why they're worth
    surfacing."""

    name = "domain_whois"

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        max_age_days = int(self.config.get("domain_whois", {}).get("recent_registration_days", 365))
        for domain in domain_candidates(target.query):
            try:
                socket.getaddrinfo(domain, 443)
            except OSError:
                continue
            result.rows_fetched += 1
            try:
                rdap = self.fetch_json(f"https://rdap.org/domain/{domain}", respect_robots=False)
            except Exception as exc:
                result.errors.append(f"{domain}: {exc}")
                continue
            events = rdap.get("events", [])
            registered = rdap_event_date(events, "registration")
            changed = rdap_event_date(events, "last changed")
            if registered is None:
                continue
            age_days = max(0, (self.utcnow() - registered).days)
            is_recent = age_days <= max_age_days
            recent_change = bool(changed and (self.utcnow() - changed).days <= max_age_days and changed != registered)
            if not is_recent and not recent_change:
                continue
            summary = f"Registered {registered.date().isoformat()} ({age_days} days ago)"
            if recent_change:
                summary += f"; last changed {changed.date().isoformat()}"
            result.findings.append(self.finding(
                source=self.name, category="general_signal",
                title=f"Domain WHOIS: {domain}",
                observed_at=changed if recent_change else registered,
                url=f"https://{domain}",
                summary=summary,
                entities=[target.query],
                raw={"domain": domain, "registered": registered.isoformat(), "changed": changed.isoformat() if changed else None},
                quiet=True,
                quiet_reason="Recent domain registration/change" + (" with no matching news" if recent_change else ""),
                dedupe_key=f"rdap:{domain}:{registered.date().isoformat()}",
            ))
        return result
