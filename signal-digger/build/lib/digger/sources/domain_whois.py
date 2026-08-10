from __future__ import annotations

import re
import socket
from datetime import datetime, timezone

from dateutil.parser import parse as parse_date

from ..models import Mode, SourceResult, Target
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


def classify_event(is_recent_registration: bool, is_recent_change: bool) -> str:
    """Which of the two RDAP events actually triggered this finding — so the report
    can say "registration" or "change" instead of the ambiguous "registration/change".
    Pure function for tests."""
    if is_recent_registration and is_recent_change:
        return "registration and change"
    return "change" if is_recent_change else "registration"


class DomainWhoisSource(BaseSource):
    """RDAP (WHOIS successor) lookups on domains guessed from the target name.
    Flags recent registrations and recent registrant/registrar changes — these
    almost never come with a press release, which is exactly why they're worth
    surfacing."""

    name = "domain_whois"
    # Guessing domains is meaningful for company names. Sector phrases and
    # people's names routinely resolve to unrelated domains and create false
    # "quiet" signals, so those modes skip transparently in Source Run Health.
    modes: tuple[Mode, ...] = ("company",)

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        source_config = self.config.get("domain_whois", {})
        registration_days = int(source_config.get("recent_registration_days", 90))
        # Fall back to the legacy single setting so existing config files keep
        # their prior behavior until the owner opts into a separate window.
        change_days = int(source_config.get("recent_change_days", registration_days))
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
            is_recent = age_days <= registration_days
            recent_change = bool(changed and (self.utcnow() - changed).days <= change_days and changed != registered)
            if not is_recent and not recent_change:
                continue
            kind = classify_event(is_recent, recent_change)
            summary = f"Registered {registered.date().isoformat()} ({age_days} days ago)"
            if recent_change:
                change_age = (self.utcnow() - changed).days
                summary += f"; registrant/registrar last changed {changed.date().isoformat()} ({change_age} days ago)"
            result.findings.append(self.finding(
                source=self.name, category="general_signal",
                title=f"Domain WHOIS: {domain} — recent {kind}",
                observed_at=changed if recent_change else registered,
                url=f"https://{domain}",
                summary=summary,
                entities=[target.query],
                raw={"domain": domain, "kind": kind, "registered": registered.isoformat(), "changed": changed.isoformat() if changed else None},
                quiet=True,
                quiet_reason=f"Recent domain {kind} with no matching news found",
                dedupe_key=f"rdap:{domain}:{registered.date().isoformat()}",
            ))
        return result
