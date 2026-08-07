from datetime import datetime, timezone

from digger.models import Finding, SourceResult


def test_finding_key_falls_back_to_composite():
    finding = Finding(source="hackernews", category="people_movement", title="Story",
                       observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), url="https://example.com/1")
    assert finding.key() == "hackernews|Story|https://example.com/1|2026-01-01"


def test_finding_key_prefers_dedupe_key():
    finding = Finding(source="s", category="general_signal", title="t",
                       observed_at=datetime.now(timezone.utc), dedupe_key="explicit-key")
    assert finding.key() == "explicit-key"


def test_source_result_status_ok_partial_failed_skipped():
    ok = SourceResult(source="s", findings=[Finding(source="s", category="general_signal", title="t", observed_at=datetime.now(timezone.utc))], rows_fetched=1)
    assert ok.status == "ok"

    partial = SourceResult(source="s", findings=[Finding(source="s", category="general_signal", title="t", observed_at=datetime.now(timezone.utc))], errors=["boom"])
    assert partial.status == "partial"

    failed = SourceResult(source="s", errors=["boom"])
    assert failed.status == "failed"

    skipped = SourceResult(source="s", skipped_reason="not applicable")
    assert skipped.status == "skipped"
