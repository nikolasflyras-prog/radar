from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from .base import BaseCollector
from ..models import CollectorResult, Signal
from ..db import normalize_name
from ..relevance import matched_terms, entity_is_excluded, entity_is_financial_vehicle, looks_like_person


class SecFormDCollector(BaseCollector):
    """Form D discovery via SEC daily master indexes and public filing XML."""
    name = "edgar"

    def _index_url(self, day: datetime) -> str:
        q = (day.month - 1) // 3 + 1
        return f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/master.{day:%Y%m%d}.idx"

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("edgar", 14)))
        keyword_cfg = self.config["keywords"]
        strong_terms = keyword_cfg.get("sec_strong_terms", keyword_cfg.get("terms", []))
        entity_morphemes = keyword_cfg.get("entity_morphemes", [])
        excluded = keyword_cfg.get("exclude_entity_terms", [])
        watched_people = {normalize_name(p["name"]) for p in self.config.get("people", [])}
        day = since.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        while day.date() <= self.utcnow().date():
            if day.weekday() >= 5:
                day += timedelta(days=1)
                continue
            try:
                text = self.get(self._index_url(day), respect_robots=False).text
            except Exception as exc:
                result.errors.append(f"{day.date()}: {exc}")
                day += timedelta(days=1)
                continue
            for line in text.splitlines():
                parts = line.split("|")
                if len(parts) != 5 or parts[2] not in {"D", "D/A"}:
                    continue
                result.rows_fetched += 1
                cik, issuer, form, filed, filename = parts
                url = "https://www.sec.gov/Archives/" + filename
                try:
                    filing = self.get(url, respect_robots=False).text
                    soup = BeautifulSoup(filing, "xml")
                    persons: list[str] = []
                    for node in soup.find_all(["relatedPersonName", "relatedPersonsName"]):
                        first = node.find(["firstName", "firstNameOfRelatedPerson"])
                        last = node.find(["lastName", "lastNameOfRelatedPerson"])
                        name = " ".join(x.get_text(strip=True) for x in (first, last) if x)
                        if looks_like_person(name):
                            persons.append(name)
                    watched_matches = [p for p in persons if normalize_name(p) in watched_people]
                    industry_parts = []
                    for tag in ("industryGroupType", "industrySubgroupType", "descriptionOfOtherIndustry", "issuerName"):
                        industry_parts.extend(x.get_text(" ", strip=True) for x in soup.find_all(tag))
                    context = " ".join(industry_parts)
                    if entity_is_excluded(issuer, context, excluded) or entity_is_financial_vehicle(issuer, context):
                        continue
                    strong_matches = matched_terms(f"{issuer} {context}", strong_terms)
                    issuer_matches = matched_terms(issuer, entity_morphemes)
                    if not watched_matches and not strong_matches and not issuer_matches:
                        continue
                    amount_node = soup.find(["totalOfferingAmount", "totalAmountSold"])
                    amount = amount_node.get_text(strip=True) if amount_node else "not disclosed"
                    if watched_matches:
                        signal_type = "form_d_watchlist_officer"
                        base_weight = None
                    elif strong_matches:
                        signal_type = "form_d_keyword_issuer"
                        base_weight = None
                    else:
                        signal_type = "form_d_discovery"
                        base_weight = 8
                    result.signals.append(Signal(
                        source=self.name,
                        signal_type=signal_type,
                        entity_name=issuer,
                        person_names=persons,
                        observed_at=parse_date(filed).replace(tzinfo=timezone.utc),
                        title=f"Form {form}: {issuer}",
                        url=url,
                        summary=(f"Offering amount: {amount}; matched terms: "
                                 f"{', '.join(strong_matches or issuer_matches) or 'watchlist person'}; "
                                 f"related people: {', '.join(persons) or 'none parsed'}"),
                        raw={"cik": cik, "form": form, "filename": filename, "offering_amount": amount,
                             "industry_context": context, "matched_terms": strong_matches or issuer_matches,
                             "watched_people": watched_matches},
                        base_weight=base_weight,
                        source_key=filename,
                    ))
                except Exception as exc:
                    result.errors.append(f"{PurePosixPath(filename).name}: {exc}")
            day += timedelta(days=1)
        return result
