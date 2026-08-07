from datetime import datetime, timedelta, timezone

from digger.models import Finding
from digger.quiet import correlate_quiet


def _finding(source, category, days_ago, **kwargs):
    return Finding(
        source=source, category=category, title=kwargs.pop("title", "t"),
        observed_at=datetime.now(timezone.utc) - timedelta(days=days_ago), **kwargs,
    )


def test_patent_with_no_nearby_news_is_flagged_quiet():
    findings = [_finding("uspto_assignments", "ma_deal", days_ago=5)]
    correlate_quiet(findings, window_days=21)
    assert findings[0].quiet is True
    assert "No news coverage" in findings[0].quiet_reason


def test_patent_with_nearby_news_is_not_flagged():
    findings = [
        _finding("uspto_assignments", "ma_deal", days_ago=5),
        _finding("news_gdelt", "ma_deal", days_ago=6),
    ]
    correlate_quiet(findings, window_days=21)
    assert findings[0].quiet is False


def test_news_outside_window_does_not_suppress_the_flag():
    findings = [
        _finding("uspto_assignments", "ma_deal", days_ago=5),
        _finding("news_gdelt", "ma_deal", days_ago=90),
    ]
    correlate_quiet(findings, window_days=21)
    assert findings[0].quiet is True


def test_already_quiet_finding_keeps_its_own_reason():
    finding = _finding("job_boards", "people_movement", days_ago=1, quiet=True, quiet_reason="Founding role")
    correlate_quiet([finding], window_days=21)
    assert finding.quiet_reason == "Founding role"


def test_non_candidate_source_is_never_auto_flagged():
    findings = [_finding("hackernews", "people_movement", days_ago=5)]
    correlate_quiet(findings, window_days=21)
    assert findings[0].quiet is False
