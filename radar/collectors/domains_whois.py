from __future__ import annotations

import re
import socket
from datetime import datetime, timedelta, timezone
from .base import BaseCollector
from ..models import CollectorResult, Signal


class DomainsRdapCollector(BaseCollector):
    name = "domains"
    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        if not self.db: result.errors.append("Domain corroboration requires the candidate database"); return result
        candidates = self.db.rows("SELECT canonical_name FROM entities WHERE first_seen >= ? ORDER BY first_seen DESC LIMIT 100",
                                  ((since or self.utcnow()-timedelta(days=30)).isoformat(),))
        for row in candidates:
            stem = re.sub(r"[^a-z0-9]", "", row["canonical_name"].casefold())
            if len(stem) < 3: continue
            for suffix in (".com", ".ai", ".io"):
                domain = stem + suffix
                try: socket.getaddrinfo(domain, 443)
                except OSError: continue
                result.rows_fetched += 1
                try:
                    rdap = self.get(f"https://rdap.org/domain/{domain}", respect_robots=False).json()
                    events = {e.get("eventAction"): e.get("eventDate") for e in rdap.get("events", [])}
                    page = self.get(f"https://{domain}").text[:200000]
                except Exception as exc: result.errors.append(f"{domain}: {exc}"); continue
                hiring = any(x in page.casefold() for x in ("hiring", "careers", "stealth", "silicon engineer"))
                observed = self.utcnow()
                result.signals.append(Signal(source=self.name, signal_type="domain_hiring" if hiring else "domain_registered",
                    entity_name=row["canonical_name"], observed_at=observed, title=f"Domain corroboration: {domain}",
                    url=f"https://{domain}", summary=f"Domain resolves; registration: {events.get('registration','unknown')}; hiring language: {hiring}",
                    raw={"domain": domain, "events": events, "hiring": hiring}, source_key=f"rdap:{domain}:{events.get('registration')}"))
        return result

