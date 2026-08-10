from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import Mode, SourceResult, Target
from .base import BaseSource

# Item numbers that typically carry deal content on an 8-K.
DEAL_ITEMS = {"1.01", "2.01"}
DEAL_FORMS = ("8-K", "S-4", "DEFM14A")


def parse_hit(hit: dict) -> dict:
    """Pull the fields we need out of one EDGAR full-text-search hit. Pure function
    so parsing can be unit tested against recorded fixtures without the network."""
    source = hit.get("_source", {})
    hit_id = hit.get("_id", "")
    accession, _, _filename = hit_id.partition(":")
    accession = accession or source.get("adsh", "")
    ciks = source.get("ciks") or []
    cik = str(ciks[0]).lstrip("0") if ciks else ""
    accession_nodash = accession.replace("-", "")
    url = None
    if cik and accession:
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{accession}-index.htm"
    items = source.get("items") or []
    return {
        "form": source.get("root_form") or source.get("form") or "",
        "file_date": source.get("file_date"),
        "display_names": source.get("display_names") or [],
        "items": items,
        "url": url,
        "accession": accession,
    }


def is_deal_relevant(parsed: dict) -> bool:
    form = parsed["form"]
    if form == "8-K":
        return bool(set(parsed["items"]) & DEAL_ITEMS) or not parsed["items"]
    return form in ("S-4", "DEFM14A")


class SecEdgarSource(BaseSource):
    """SEC EDGAR full-text search for 8-K (Item 1.01/2.01), S-4, and DEFM14A filings
    naming the target. Company/sector targets only — EDGAR full-text search indexes
    filing text, not individual officers, so person mode is skipped."""

    name = "sec_edgar"
    modes: tuple[Mode, ...] = ("company", "sector")
    endpoint = "https://efts.sec.gov/LATEST/search-index"

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        params = {
            "q": f'"{target.query}"',
            "forms": ",".join(DEAL_FORMS),
            "startdt": since.date().isoformat(),
            "enddt": self.utcnow().date().isoformat(),
        }
        try:
            payload = self.fetch_json(self.endpoint, params=params, respect_robots=False)
        except Exception as exc:
            result.errors.append(f"full-text search: {exc}")
            return result
        hits = (payload.get("hits") or {}).get("hits") or []
        result.rows_fetched = len(hits)
        for hit in hits:
            parsed = parse_hit(hit)
            if not is_deal_relevant(parsed):
                continue
            try:
                observed = datetime.fromisoformat(parsed["file_date"]).replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                observed = self.utcnow()
            names = parsed["display_names"]
            item_note = f"; items {', '.join(parsed['items'])}" if parsed["items"] else ""
            result.findings.append(self.finding(
                source=self.name, category="ma_deal",
                title=f"{parsed['form']} filing: {'; '.join(names) or target.query}",
                observed_at=observed, url=parsed["url"],
                summary=f"Form {parsed['form']} naming {target.query}{item_note}",
                entities=names or [target.query],
                raw={"form": parsed["form"], "items": parsed["items"], "accession": parsed["accession"]},
                dedupe_key=f"edgar:{parsed['accession']}",
            ))
        return result
