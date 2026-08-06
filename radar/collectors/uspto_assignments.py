from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from dateutil.parser import parse as parse_date
from pathlib import Path
from lxml import etree
from .base import BaseCollector
from ..models import CollectorResult, Signal


class UsptoAssignmentsCollector(BaseCollector):
    """Patent assignment collector.

    The public Assignment Search service has changed interfaces repeatedly. Its
    query URL is configurable; failures are isolated and reported. For durable
    backfills, README documents the official bulk XML route.
    """
    name = "uspto"

    def _bulk(self, since: datetime, org_names: list[str]) -> CollectorResult:
        result = CollectorResult(source=self.name)
        bulk_dir = self.config.get("sources", {}).get("uspto_bulk_xml_dir")
        if not bulk_dir: return result
        root = Path(self.config["root"]) / bulk_dir
        if not root.exists():
            result.errors.append(f"Configured USPTO bulk directory does not exist: {root}")
            return result
        for path in sorted(root.glob("*.xml")):
            try:
                context = etree.iterparse(str(path), events=("end",), recover=True, huge_tree=True)
                for _, elem in context:
                    if etree.QName(elem).localname != "patent-assignment": continue
                    result.rows_fetched += 1
                    def texts(local):
                        return [str(x).strip() for x in elem.xpath(f".//*[local-name()='{local}']/text()") if str(x).strip()]
                    assignors = texts("assignor-name"); assignees = texts("assignee-name")
                    recorded = next(iter(texts("recorded-date")), "")
                    try: observed = parse_date(recorded).replace(tzinfo=timezone.utc)
                    except Exception: observed = self.utcnow()
                    assignor = ", ".join(assignors); assignee = ", ".join(assignees)
                    if observed < since or not assignee or not any(o.casefold() in assignor.casefold() for o in org_names):
                        elem.clear(); continue
                    reel = next(iter(texts("reel-no")), ""); frame = next(iter(texts("frame-no")), "")
                    raw = {"assignors": assignors, "assignees": assignees, "recorded_date": recorded,
                           "patent_numbers": texts("document-id"), "correspondent": texts("correspondent-name")}
                    result.signals.append(Signal(source=self.name, signal_type="patent_bigco_to_new", entity_name=assignee,
                        observed_at=observed, title=f"Patent assignment: {assignor} → {assignee}",
                        summary=f"Recorded {recorded}; bulk XML {path.name}", raw=raw,
                        source_key=f"uspto-bulk:{reel}:{frame}:{assignor}:{assignee}"))
                    elem.clear()
            except Exception as exc: result.errors.append(f"bulk {path.name}: {exc}")
        return result

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("uspto", 30)))
        endpoint = self.config.get("sources", {}).get("uspto_assignment_endpoint", "https://assignment-api.uspto.gov/patent/basicSearch")
        org_names = [org["name"] if isinstance(org, dict) else org for org in self.config.get("orgs", [])]
        any_live_success = False
        for name in org_names:
            params = {"query": name, "startDate": since.date().isoformat(), "rows": 100}
            try: payload = self.get(endpoint, params=params, respect_robots=False).json()
            except Exception as exc: result.errors.append(f"{name}: live API unavailable ({exc}); use bulk XML backfill"); continue
            any_live_success = True
            docs = payload.get("docs") or payload.get("results") or payload.get("patentAssignments") or []
            result.rows_fetched += len(docs)
            for doc in docs:
                assignors = doc.get("assignors") or doc.get("assignorNames") or []
                assignees = doc.get("assignees") or doc.get("assigneeNames") or []
                assignor = ", ".join(x.get("name", "") if isinstance(x, dict) else str(x) for x in assignors)
                assignee = ", ".join(x.get("name", "") if isinstance(x, dict) else str(x) for x in assignees)
                if not assignee or name.casefold() not in assignor.casefold(): continue
                raw_date = doc.get("recordedDate") or doc.get("recorded_date") or self.utcnow().isoformat()
                try: observed = parse_date(raw_date)
                except Exception: observed = self.utcnow()
                if observed.tzinfo is None: observed = observed.replace(tzinfo=timezone.utc)
                key = str(doc.get("reelFrame") or doc.get("id") or f"{assignor}:{assignee}:{raw_date}")
                result.signals.append(Signal(source=self.name, signal_type="patent_bigco_to_new", entity_name=assignee,
                    observed_at=observed, title=f"Patent assignment: {assignor} → {assignee}",
                    url=doc.get("assignmentUrl"), summary=f"Recorded {raw_date}; correspondent: {doc.get('correspondentName','unknown')}",
                    raw=doc, source_key=f"uspto:{key}"))
        if not any_live_success:
            bulk = self._bulk(since, org_names)
            result.rows_fetched += bulk.rows_fetched; result.signals.extend(bulk.signals); result.errors.extend(bulk.errors)
        return result
