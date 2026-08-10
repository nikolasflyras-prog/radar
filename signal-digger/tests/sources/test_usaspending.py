from datetime import datetime, timezone

import responses

from digger.cache import ResponseCache
from digger.models import Target
from digger.sources.usaspending import UsaSpendingSource, parse_award


def test_parse_award_normalizes_human_readable_fields():
    award = parse_award({
        "Award ID": "FA123",
        "Recipient Name": "Photonics Labs",
        "Start Date": "2026-08-01",
        "Award Amount": 2500000,
        "Awarding Agency": "Department of Defense",
        "Description": "Optical interconnect development",
    }, datetime.now(timezone.utc))
    assert award["recipient"] == "Photonics Labs"
    assert award["amount"] == 2500000


@responses.activate
def test_collect_posts_advanced_search_and_returns_award(tmp_path):
    responses.add(
        responses.POST, "https://api.usaspending.gov/api/v2/search/spending_by_award/",
        json={"results": []}, status=200,
    )
    responses.add(
        responses.POST, "https://api.usaspending.gov/api/v2/search/spending_by_award/",
        json={"results": [{
            "Award ID": "FA123", "Recipient Name": "Photonics Labs", "Start Date": "2026-08-01",
            "Award Amount": 2500000, "Awarding Agency": "Department of Defense",
            "Description": "Optical interconnect development",
        }]}, status=200,
    )
    config = {"contact_email": "t@example.com", "timeout_seconds": 5, "rate_limit_seconds": 0,
              "rate_limits": {}, "cache": {"ttl_hours": {"default": 0}}, "lookback_days": 30}
    source = UsaSpendingSource(config, cache=ResponseCache(tmp_path / "cache.db"), use_cache=False)
    result = source.collect(Target(mode="sector", query="optical interconnects"))
    assert len(result.findings) == 1
    assert "$2,500,000" in result.findings[0].summary
    assert len(responses.calls) == 2
    request_groups = [call.request.body.decode() if isinstance(call.request.body, bytes) else call.request.body
                      for call in responses.calls]
    assert '"award_type_codes": ["A", "B", "C", "D"]' in request_groups[0]
    assert '"award_type_codes": ["02", "03", "04", "05"]' in request_groups[1]
