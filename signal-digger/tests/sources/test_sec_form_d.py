from datetime import datetime, timezone

import responses

from digger.cache import ResponseCache
from digger.models import Target
from digger.sources.sec_form_d import SecFormDSource


@responses.activate
def test_collect_returns_form_d_filing(tmp_path):
    responses.add(
        responses.GET, "https://efts.sec.gov/LATEST/search-index",
        json={"hits": {"hits": [{
            "_id": "0001234567-26-000001:primary_doc.xml",
            "_source": {"root_form": "D", "file_date": "2026-08-09", "display_names": ["Photonics Labs Inc"], "ciks": ["1234567"]},
        }]}}, status=200,
    )
    config = {"contact_email": "t@example.com", "timeout_seconds": 5, "rate_limit_seconds": 0,
              "rate_limits": {}, "cache": {"ttl_hours": {"default": 0}}, "lookback_days": 30}
    source = SecFormDSource(config, cache=ResponseCache(tmp_path / "cache.db"), use_cache=False)
    result = source.collect(Target(mode="company", query="Photonics Labs"))
    assert len(result.findings) == 1
    assert result.findings[0].quiet
    assert "private financing" in result.findings[0].title
