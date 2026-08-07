from datetime import datetime, timedelta, timezone
from pathlib import Path

from digger.models import Finding, SourceResult, Target
from digger.report import build_report_context, compile_report, dedupe, render_html_report, write_report, write_reports


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


def test_render_html_report_contains_expected_sections_and_escapes_content():
    finding = _finding(title="<script>alert(1)</script> acquires Widgets", dedupe_key="xss")
    target = Target(mode="company", query="Acme")
    ctx = build_report_context(target, [SourceResult(source="news_gdelt", findings=[finding])], {})
    page = render_html_report(target, ctx)

    assert "<!doctype html>" in page.lower()
    assert "<title>Signal Digger: Acme</title>" in page
    assert "Quiet signals worth a second look" in page
    assert "M&amp;A &amp; Deal Activity" in page
    assert "Source Run Health" in page
    # The finding title is HTML-escaped, not injected as raw markup.
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_render_html_report_marks_quiet_findings_with_their_reason():
    quiet = _finding(source="uspto_assignments", title="Quiet patent move", dedupe_key="q",
                      quiet=True, quiet_reason="No matching news coverage found")
    target = Target(mode="company", query="Acme")
    ctx = build_report_context(target, [SourceResult(source="uspto_assignments", findings=[quiet])], {})
    page = render_html_report(target, ctx)
    assert "Quiet patent move" in page
    assert "No matching news coverage found" in page


def test_quiet_section_keeps_the_finding_summary_alongside_the_reason():
    # A source's quiet_reason states the category of thing that happened (e.g.
    # "registration" vs "change" for domain_whois); the specifics — dates, etc. —
    # live in .summary and must not be dropped just because a finding is quiet.
    quiet = _finding(source="domain_whois", title="Domain WHOIS: acme.com — recent change", dedupe_key="dw",
                      summary="Registered 2010-01-01 (5000 days ago); registrant/registrar last changed 2026-07-24 (14 days ago)",
                      quiet=True, quiet_reason="Recent domain change with no matching news found")
    target = Target(mode="company", query="Acme")
    ctx = build_report_context(target, [SourceResult(source="domain_whois", findings=[quiet])], {})

    markdown = compile_report(target, [SourceResult(source="domain_whois", findings=[quiet])], {})
    assert "Recent domain change with no matching news found" in markdown
    assert "registrant/registrar last changed 2026-07-24" in markdown

    page = render_html_report(target, ctx)
    assert "Recent domain change with no matching news found" in page
    assert "registrant/registrar last changed 2026-07-24" in page


def test_write_reports_produces_a_matching_md_and_html_pair(tmp_path: Path):
    target = Target(mode="company", query="Acme")
    results = [SourceResult(source="news_gdelt", findings=[_finding(dedupe_key="a")])]
    md_path, html_path = write_reports(target, results, {}, tmp_path)

    assert md_path.exists() and html_path.exists()
    assert md_path.suffix == ".md"
    assert html_path.suffix == ".html"
    # Same run, same timestamp/slug — only the extension should differ.
    assert md_path.stem == html_path.stem
    assert "Acme acquires Widgets" in md_path.read_text()
    assert "Acme acquires Widgets" in html_path.read_text()
