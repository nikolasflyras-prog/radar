from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import Mode, SourceResult, Target
from .base import BaseSource
from .sec_edgar import parse_hit


class SecFormDSource(BaseSource):
    """SEC Form D and D/A filings that can reveal private financings."""

    name = "sec_form_d"
    modes: tuple[Mode, ...] = ("company", "sector")
    endpoint = "https://efts.sec.gov/LATEST/search-index"

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        params = {
            "q": f'"{target.query}"',
            "forms": "D,D/A",
            "startdt": since.date().isoformat(),
            "enddt": self.utcnow().date().isoformat(),
        }
        try:
            payload = self.fetch_json(self.endpoint, params=params, respect_robots=False)
        except Exception as exc:
            result.errors.append(f"Form D search: {exc}")
            return result
        hits = (payload.get("hits") or {}).get("hits") or []
        result.rows_fetched = len(hits)
        for hit in hits:
            parsed = parse_hit(hit)
            try:
                observed = datetime.fromisoformat(str(parsed["file_date"])).replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                observed = self.utcnow()
            names = parsed["display_names"] or [target.query]
            result.findings.append(self.finding(
                source=self.name,
                category="ma_deal",
                title=f"{parsed['form'] or 'Form D'} private financing filing: {'; '.join(names)}",
                observed_at=observed,
                url=parsed["url"],
                summary="SEC notice of an exempt private securities offering; review the filing for amount sold, total offering, and investors.",
                entities=names,
                raw={"form": parsed["form"], "accession": parsed["accession"]},
                quiet=True,
                quiet_reason="Private financing filing may precede a public funding announcement",
                dedupe_key=f"form-d:{parsed['accession']}",
            ))
        return result
