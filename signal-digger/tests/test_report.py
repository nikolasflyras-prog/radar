from datetime import datetime, timedelta, timezone
from pathlib import Path

from digger.models import Finding, SourceResult, Target
from digger.report import compile_report, dedupe, write_report


def _finding(**overrides):
    defaults = dict(source="news_gdelt", category="ma_deal", title="Acme acquires Widgets",
                     observed_at=datetime.now(timezone.utc), url="https://example.com/a")
    defaults.update(overrides)
    return Finding(**defaults)


def test_dedupe_keeps_one_per_key():
    findings = [_finding(dedupe_key="dup"), _finding(dedupe_key="dup"), _finding(dedupe_key="unique")]
    assert len(dedupe(findings)) == 2


def test_compile_report_sections_and_sort_order():
    older = _finding(title="Older deal", observed_at=datetime.now(timezone.utc) - timedelta(days=10), dedupe_key="old")
    newer = _finding(title="Newer deal", observed_at=datetime.now(timezone.utc), dedupe_key="new")
    quiet_finding = _finding(source="uspto_assignments", title="Quiet patent move",
                              observed_at=datetime.now(timezone.utc) - timedelta(days=1), dedupe_key="quiet",
                              quiet=True, quiet_reason="No matching news coverage found")
    results = [SourceResult(source="news_gdelt", findings=[older, newer], rows_fetched=2),
               SourceResult(source="uspto_assignments", findings=[quiet_finding], rows_fetched=1)]
    target = Target(mode="company", query="Acme")
    markdown = compile_report(target, results, {"quiet_signals": {"correlation_window_days": 21}})

    assert "# Signal Digger Report: Acme" in markdown
    assert "## Quiet signals worth a second look" in markdown
    assert "Quiet patent move" in markdown.split("## M&A")[0]
    # Newest-first within the M&A section.
    ma_section = markdown.split("## M&A & Deal Activity")[1].split("## People")[0]
    assert ma_section.index("Newer deal") < ma_section.index("Older deal")
    assert "## Source Run Health" in markdown
    assert "news_gdelt" in markdown and "uspto_assignments" in markdown


def test_compile_report_handles_empty_sections():
    target = Target(mode="person", query="Jane Chen")
    markdown = compile_report(target, [], {})
    assert "- None this run." in markdown
    assert "- No findings this run." in markdown


def test_write_report_creates_a_slugged_file(tmp_path: Path):
    target = Target(mode="company", query="Acme, Inc.")
    path = write_report("# report\n", tmp_path, target)
    assert path.exists()
    assert path.parent == tmp_path
    assert path.name.startswith("company-acme-")
