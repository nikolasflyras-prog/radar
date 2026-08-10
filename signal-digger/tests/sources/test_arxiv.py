from datetime import datetime, timezone

import responses

from digger.cache import ResponseCache
from digger.models import Target
from digger.sources.arxiv import ArxivSource, parse_entry


def test_parse_entry_normalizes_authors_and_date():
    parsed = parse_entry({
        "id": "https://arxiv.org/abs/2608.12345",
        "title": "  Optical   I/O for Chiplets ",
        "published": "2026-08-08T12:00:00Z",
        "authors": [{"name": "Jane Chen"}],
    }, datetime.now(timezone.utc))
    assert parsed["title"] == "Optical I/O for Chiplets"
    assert parsed["authors"] == ["Jane Chen"]
    assert parsed["observed"].year == 2026


@responses.activate
def test_collect_returns_recent_paper(tmp_path):
    responses.add(responses.GET, "https://export.arxiv.org/api/query", body="""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>https://arxiv.org/abs/2608.12345</id><updated>2026-08-09T12:00:00Z</updated>
      <published>2026-08-09T12:00:00Z</published><title>Optical I/O for Chiplets</title>
      <summary>A co-packaged optics architecture.</summary><author><name>Jane Chen</name></author></entry>
    </feed>""", status=200)
    config = {"contact_email": "t@example.com", "timeout_seconds": 5, "rate_limit_seconds": 0,
              "rate_limits": {}, "cache": {"ttl_hours": {"default": 0}}, "lookback_days": 30}
    source = ArxivSource(config, cache=ResponseCache(tmp_path / "cache.db"), use_cache=False)
    result = source.collect(Target(mode="sector", query="optical interconnects"))
    assert len(result.findings) == 1
    assert result.findings[0].people == ["Jane Chen"]
