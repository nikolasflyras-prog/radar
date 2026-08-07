from __future__ import annotations

from datetime import timedelta, timezone

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from ..models import Mode, SourceResult, Target
from ..textutil import mentions_target
from .base import BaseSource

DEFAULT_LISTING_URL = "https://www.ftc.gov/legal-library/browse/early-termination-notices"


def parse_listing_html(html: str, query: str) -> list[dict]:
    """Parse the FTC HSR early-termination-notices listing table into rows that
    mention `query` in the party names. Pure function, testable against a fixture —
    the FTC page is a plain HTML table of (grant date, parties, transaction #)."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    for tr in soup.select("table tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 2 or not cells[0][:1].isdigit():
            continue
        date_text, parties = cells[0], cells[1]
        if not mentions_target(parties, query):
            continue
        link = tr.find("a")
        rows.append({
            "date_text": date_text,
            "parties": parties,
            "transaction_number": cells[2] if len(cells) > 2 else "",
            "url": link["href"] if link and link.get("href") else None,
        })
    return rows


class FtcHsrSource(BaseSource):
    """FTC Hart-Scott-Rodino early termination notices — public confirmation that a
    reportable acquisition cleared antitrust waiting period review. Company/sector
    targets only."""

    name = "ftc_hsr"
    modes: tuple[Mode, ...] = ("company", "sector")

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        listing_url = self.config.get("ftc_hsr", {}).get("listing_url", DEFAULT_LISTING_URL)
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        try:
            html = self.fetch_text(listing_url)
        except Exception as exc:
            result.errors.append(f"listing page: {exc}")
            return result
        rows = parse_listing_html(html, target.query)
        result.rows_fetched = len(rows)
        for row in rows:
            try:
                observed = parse_date(row["date_text"])
                observed = observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed.astimezone(timezone.utc)
            except (ValueError, OverflowError):
                observed = self.utcnow()
            if observed < since:
                continue
            url = row["url"]
            if url and url.startswith("/"):
                url = f"https://www.ftc.gov{url}"
            result.findings.append(self.finding(
                source=self.name, category="ma_deal",
                title=f"HSR early termination: {row['parties']}",
                observed_at=observed, url=url or listing_url,
                summary=f"Early termination granted; transaction {row['transaction_number'] or 'unnumbered'}",
                entities=[target.query],
                raw=row,
                dedupe_key=f"ftc_hsr:{row['transaction_number'] or row['parties']}:{row['date_text']}",
            ))
        return result
