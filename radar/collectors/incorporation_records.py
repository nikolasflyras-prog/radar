from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from dateutil.parser import parse as parse_date
from .base import BaseCollector
from ..models import CollectorResult, Signal


class IncorporationRecordsCollector(BaseCollector):
    name = "incorporation"
    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("incorporation", 30)))
        token = self.config.get("tokens", {}).get("opencorporates")
        if not token:
            result.errors.append("OpenCorporates token absent; set OPENCORPORATES_TOKEN. Delaware has no free bulk search and is intentionally unsupported.")
            return result
        for term in self.config["keywords"].get("entity_morphemes", [])[:30]:
            url = "https://api.opencorporates.com/v0.4/companies/search"
            try: payload = self.get(url, params={"q": term, "created_at": f">={since.date()}", "api_token": token}, respect_robots=False).json()
            except Exception as exc: result.errors.append(f"{term}: {exc}"); continue
            companies = payload.get("results", {}).get("companies", [])
            result.rows_fetched += len(companies)
            for wrapper in companies:
                co = wrapper.get("company", wrapper)
                try: observed = parse_date(co.get("incorporation_date") or since.date().isoformat()).replace(tzinfo=timezone.utc)
                except Exception: observed = self.utcnow()
                result.signals.append(Signal(source=self.name, signal_type="new_incorporation_keyword", entity_name=co.get("name"),
                    observed_at=observed, title=f"New keyword-matching entity: {co.get('name')}", url=co.get("opencorporates_url"),
                    summary=f"{co.get('jurisdiction_code')} registry; matched '{term}'", raw=co,
                    source_key=f"oc:{co.get('company_number')}:{co.get('jurisdiction_code')}"))
        return result

