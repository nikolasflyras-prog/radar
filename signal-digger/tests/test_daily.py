from datetime import datetime, timezone

from digger.daily import DailySeenStore, QuerySpec, build_daily_payload, canonical_url, load_query_specs, run_daily
from digger.models import Finding


def _finding(source="news_rss", url="https://example.com/story?utm_source=test"):
    return Finding(
        source=source,
        category="ma_deal",
        title="Acme raises a new financing round",
        observed_at=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
        url=url,
        summary="Financing summary",
        entities=["Acme"],
    )


def test_canonical_url_removes_tracking_parameters():
    assert canonical_url("https://Example.com/story/?utm_source=x&id=4#top") == "https://example.com/story?id=4"


def test_load_query_specs(tmp_path):
    path = tmp_path / "searches.yaml"
    path.write_text("searches:\n  - name: Optical I/O\n    mode: sector\n    query: optical interconnects\n    sources: [arxiv, news_rss]\n")
    specs = load_query_specs(path)
    assert specs == [QuerySpec("Optical I/O", "sector", "optical interconnects", ("arxiv", "news_rss"))]


def test_payload_deduplicates_across_queries_and_sources(tmp_path):
    store = DailySeenStore(tmp_path / "daily.db")
    one = QuerySpec("Optical I/O", "sector", "optical interconnects")
    two = QuerySpec("Silicon Photonics", "sector", "silicon photonics")
    matched = [
        (one, _finding("news_rss")),
        (two, _finding("news_gdelt", "https://example.com/story?utm_campaign=other")),
    ]
    payload = build_daily_payload(matched, [], store, generated_at=datetime(2026, 8, 10, 13, tzinfo=timezone.utc))
    assert len(payload["findings"]) == 1
    item = payload["findings"][0]
    assert item["sources"] == ["news_rss", "news_gdelt"]
    assert item["searches"] == ["Optical I/O", "Silicon Photonics"]
    assert item["is_new"] is True


def test_payload_suppresses_previously_seen_items(tmp_path):
    store = DailySeenStore(tmp_path / "daily.db")
    spec = QuerySpec("Optical I/O", "sector", "optical interconnects")
    first = build_daily_payload([(spec, _finding())], [], store)
    second = build_daily_payload([(spec, _finding())], [], store)
    assert len(first["findings"]) == 1
    assert second["findings"] == []


def test_run_daily_can_collect_without_publishing(tmp_path):
    config = {"daily": {"publish_url": "https://example.com/ingest", "state_path": "daily.db"}}
    payload = run_daily([], config, cache_root=tmp_path, publish=False)
    assert payload["summary"]["published_findings"] == 0
