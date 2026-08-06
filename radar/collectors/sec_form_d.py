from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from .base import BaseCollector
from ..models import CollectorResult, Signal
from ..db import normalize_name


class SecFormDCollector(BaseCollector):
    """Form D discovery via SEC daily master indexes and public filing XML."""
    name = "edgar"

    def _index_url(self, day: datetime) -> str:
        q = (day.month - 1) // 3 + 1
        return f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/master.{day:%Y%m%d}.idx"

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("edgar", 14)))
        keywords = [k.casefold() for k in self.config["keywords"].get("terms", [])]
        day = since.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        while day.date() <= self.utcnow().date():
            if day.weekday() >= 5:
                day += timedelta(days=1); continue
            try:
                text = self.get(self._index_url(day), respect_robots=False).text
            except Exception as exc:
                result.errors.append(f"{day.date()}: {exc}"); day += timedelta(days=1); continue
            for line in text.splitlines():
                parts = line.split("|")
                if len(parts) != 5 or parts[2] not in {"D", "D/A"}: continue
                result.rows_fetched += 1
                cik, issuer, form, filed, filename = parts
                url = "https://www.sec.gov/Archives/" + filename
                try:
                    filing = self.get(url, respect_robots=False).text
                    soup = BeautifulSoup(filing, "xml")
                    blob = soup.get_text(" ", strip=True)
                    if keywords and not any(k in blob.casefold() or k in issuer.casefold() for k in keywords): continue
                    persons = []
                    for node in soup.find_all(["relatedPersonName", "relatedPersonsName"]):
                        first = node.find(["firstName", "firstNameOfRelatedPerson"])
                        last = node.find(["lastName", "lastNameOfRelatedPerson"])
                        name = " ".join(x.get_text(strip=True) for x in (first, last) if x)
                        if name: persons.append(name)
                    amount_node = soup.find(["totalOfferingAmount", "totalAmountSold"])
                    amount = amount_node.get_text(strip=True) if amount_node else "not disclosed"
                    watched_people = {normalize_name(p["name"]) for p in self.config.get("people", [])}
                    signal_type = "form_d_watchlist_officer" if any(normalize_name(p) in watched_people for p in persons) else "form_d_keyword_issuer"
                    result.signals.append(Signal(source=self.name, signal_type=signal_type, entity_name=issuer,
                        person_names=persons, observed_at=parse_date(filed).replace(tzinfo=timezone.utc), title=f"Form {form}: {issuer}",
                        url=url, summary=f"Form D offering amount: {amount}; related people: {', '.join(persons) or 'none parsed'}",
                        raw={"cik": cik, "form": form, "filename": filename, "offering_amount": amount}, source_key=filename))
                except Exception as exc:
                    result.errors.append(f"{PurePosixPath(filename).name}: {exc}")
            day += timedelta(days=1)
        return result
