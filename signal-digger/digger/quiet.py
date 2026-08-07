from __future__ import annotations

from datetime import timedelta

from .models import Finding

# Sources whose findings are inherently quiet: they rarely get press coverage on
# their own, so a nearby news item (or lack of one) is the signal.
CORRELATION_CANDIDATE_SOURCES = {"uspto_assignments", "job_boards", "domain_whois"}
NEWS_SOURCES = {"news_gdelt", "news_rss", "sec_edgar", "ftc_hsr"}


def correlate_quiet(findings: list[Finding], window_days: int) -> None:
    """Mutate `findings` in place: flag any finding from a quiet-prone source that
    has no news finding within `window_days` of it, on top of whatever a source
    already flagged directly (e.g. a "Founding Engineer" posting, a domain
    re-registration). Pure over the list — no I/O — so it's cheap to unit test."""
    news_dates = [f.observed_at for f in findings if f.source in NEWS_SOURCES]
    for finding in findings:
        if finding.quiet or finding.source not in CORRELATION_CANDIDATE_SOURCES:
            continue
        start, end = finding.observed_at - timedelta(days=window_days), finding.observed_at + timedelta(days=window_days)
        if not any(start <= d <= end for d in news_dates):
            finding.quiet = True
            finding.quiet_reason = f"No news coverage found within {window_days} days of this event"
