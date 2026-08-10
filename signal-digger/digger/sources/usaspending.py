from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import SourceResult, Target
from .base import BaseSource


AWARD_TYPE_CODES = ["A", "B", "C", "D", "02", "03", "04", "05"]


def parse_award(row: dict, fallback: datetime) -> dict:
    date_value = row.get("Start Date") or row.get("start_date") or row.get("Date Signed")
    try:
        observed = datetime.fromisoformat(str(date_value)).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        observed = fallback
    award_id = row.get("generated_internal_id") or row.get("Award ID") or row.get("award_id") or ""
    amount = row.get("Award Amount") if row.get("Award Amount") is not None else row.get("award_amount")
    return {
        "award_id": str(award_id),
        "recipient": row.get("Recipient Name") or row.get("recipient_name") or "Unknown recipient",
        "agency": row.get("Awarding Agency") or row.get("awarding_agency_name") or "Unknown agency",
        "description": " ".join(str(row.get("Description") or row.get("description") or "").split()),
        "amount": float(amount or 0),
        "observed": observed,
    }


class UsaSpendingSource(BaseSource):
    """Recent U.S. federal contracts and grants matching the research target."""

    name = "usaspending"
    endpoint = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    modes = ("company", "sector")

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        lookback = int(self.config.get("lookback_days", 90))
        since = self.utcnow() - timedelta(days=lookback)
        body = {
            "filters": {
                "time_period": [{"start_date": since.date().isoformat(), "end_date": self.utcnow().date().isoformat()}],
                "keywords": [target.query],
                "award_type_codes": AWARD_TYPE_CODES,
            },
            "fields": ["Award ID", "Recipient Name", "Start Date", "Award Amount", "Awarding Agency", "Description"],
            "page": 1,
            "limit": max(1, min(100, int(self.config.get("usaspending", {}).get("limit", 50)))),
            "subawards": False,
        }
        try:
            payload = self.fetch_json(self.endpoint, method="POST", json_data=body, respect_robots=False)
        except Exception as exc:
            result.errors.append(f"award search: {exc}")
            return result
        rows = payload.get("results") or []
        result.rows_fetched = len(rows)
        for raw_row in rows:
            award = parse_award(raw_row, self.utcnow())
            amount_text = f"${award['amount']:,.0f}" if award["amount"] else "amount undisclosed"
            result.findings.append(self.finding(
                source=self.name,
                category="general_signal",
                title=f"Federal award: {award['recipient']}",
                observed_at=award["observed"],
                url=f"https://www.usaspending.gov/award/{award['award_id']}" if award["award_id"] else "https://www.usaspending.gov/search",
                summary=f"{amount_text} from {award['agency']} — {award['description'][:360]}",
                entities=[target.query, award["recipient"], award["agency"]],
                raw=award,
                quiet=True,
                quiet_reason="Government award with limited accompanying industry coverage",
                dedupe_key=f"usaspending:{award['award_id'] or award['recipient'] + str(award['observed'].date())}",
            ))
        return result
