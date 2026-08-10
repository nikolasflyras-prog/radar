from datetime import datetime, timezone

from digger.models import Target
from digger.sources.openalex import OpenAlexSource, parse_work


def test_parse_work_extracts_people_and_institutions():
    parsed = parse_work({
        "id": "https://openalex.org/W1",
        "display_name": "Chiplet interconnect paper",
        "publication_date": "2026-08-08",
        "cited_by_count": 3,
        "authorships": [{"author": {"display_name": "Jane Chen"}, "institutions": [{"display_name": "MIT"}]}],
        "primary_location": {"landing_page_url": "https://example.com/paper"},
    }, datetime.now(timezone.utc))
    assert parsed["authors"] == ["Jane Chen"]
    assert parsed["institutions"] == ["MIT"]
    assert parsed["citations"] == 3


def test_source_skips_without_key():
    source = OpenAlexSource({"tokens": {}}, cache=None, use_cache=False)
    result = source.collect(Target(mode="sector", query="chiplets"))
    assert result.status == "skipped"
    assert "OPENALEX_API_KEY" in result.skipped_reason
