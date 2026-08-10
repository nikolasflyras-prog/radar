from datetime import datetime, timedelta, timezone

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


def test_payload_classifies_material_updates(tmp_path):
    store = DailySeenStore(tmp_path / "daily.db")
    spec = QuerySpec("Optical I/O", "sector", "optical interconnects")
    first = build_daily_payload([(spec, _finding())], [], store)
    changed = _finding()
    changed.summary = "Financing summary with a newly disclosed $40 million amount"
    second = build_daily_payload([(spec, changed)], [], store)
    assert first["findings"][0]["status"] == "new"
    assert second["findings"][0]["status"] == "updated"
    assert second["summary"]["updated_events"] == 1


def test_payload_classifies_new_source_as_corroboration(tmp_path):
    store = DailySeenStore(tmp_path / "daily.db")
    spec = QuerySpec("Optical I/O", "sector", "optical interconnects")
    build_daily_payload([(spec, _finding("news_rss"))], [], store)
    second = build_daily_payload([(spec, _finding("news_gdelt"))], [], store)
    assert second["findings"][0]["status"] == "corroborated"


def test_payload_marks_event_resurfaced_after_thirty_days(tmp_path):
    store = DailySeenStore(tmp_path / "daily.db")
    spec = QuerySpec("Optical I/O", "sector", "optical interconnects")
    first_day = datetime(2026, 6, 1, tzinfo=timezone.utc)
    build_daily_payload([(spec, _finding())], [], store, generated_at=first_day)
    later = build_daily_payload(
        [(spec, _finding())], [], store,
        generated_at=first_day + timedelta(days=31),
    )
    assert later["findings"][0]["status"] == "resurfaced"


def test_payload_clusters_syndicated_near_duplicate_titles(tmp_path):
    store = DailySeenStore(tmp_path / "daily.db")
    spec = QuerySpec("Optical I/O", "sector", "optical interconnects")
    first = _finding("news_rss", "https://publisher.example/story")
    second = _finding("news_gdelt", "https://syndicator.example/acme")
    second.title = "Acme announces new financing round"
    payload = build_daily_payload([(spec, first), (spec, second)], [], store)
    assert len(payload["findings"]) == 1
    assert payload["summary"]["duplicate_observations"] == 1
    assert payload["findings"][0]["sources"] == ["news_rss", "news_gdelt"]


def test_run_daily_can_collect_without_publishing(tmp_path):
    config = {"daily": {"publish_url": "https://example.com/ingest", "state_path": "daily.db"}}
    payload = run_daily([], config, cache_root=tmp_path, publish=False)
    assert payload["summary"]["published_findings"] == 0
