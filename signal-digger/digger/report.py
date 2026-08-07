from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .models import Finding, SourceResult, Target
from .quiet import correlate_quiet
from .textutil import normalize

CATEGORY_TITLES = {
    "ma_deal": "M&A & Deal Activity",
    "people_movement": "People & Staff Movement",
    "general_signal": "General & Other Signals",
}


def dedupe(findings: list[Finding]) -> list[Finding]:
    seen: dict[str, Finding] = {}
    for finding in findings:
        seen.setdefault(finding.key(), finding)
    return list(seen.values())


def newest_first(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: f.observed_at, reverse=True)


def _date(finding: Finding) -> str:
    return finding.observed_at.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _link(finding: Finding) -> str:
    return f"[{finding.title}]({finding.url})" if finding.url else finding.title


def _finding_line(finding: Finding) -> str:
    who = f"; people: {', '.join(finding.people)}" if finding.people else ""
    summary = f" — {finding.summary}" if finding.summary else ""
    return f"- **{_date(finding)}** — {_link(finding)} — _{finding.source}_{who}{summary}"


def all_findings(results: list[SourceResult]) -> list[Finding]:
    findings: list[Finding] = []
    for result in results:
        findings.extend(result.findings)
    return findings


def compile_report(target: Target, results: list[SourceResult], config: dict) -> str:
    findings = dedupe(all_findings(results))
    window_days = int(config.get("quiet_signals", {}).get("correlation_window_days", 21))
    correlate_quiet(findings, window_days)

    lines = [
        f"# Signal Digger Report: {target.query}",
        f"_Mode: {target.mode} · Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_",
        "",
        "## Quiet signals worth a second look",
        "Findings that don't fit neatly elsewhere, or arrived with no matching news coverage nearby.",
    ]
    quiet = newest_first([f for f in findings if f.quiet])
    if quiet:
        lines += [f"- **{_date(f)}** — {_link(f)} — _{f.source}_ — {f.quiet_reason or 'flagged quiet'}" for f in quiet]
    else:
        lines.append("- None this run.")
    lines.append("")

    for category, title in CATEGORY_TITLES.items():
        items = newest_first([f for f in findings if f.category == category])
        lines.append(f"## {title}")
        lines += [_finding_line(f) for f in items] if items else ["- No findings this run."]
        lines.append("")

    lines.append("## Source Run Health")
    lines.append("Every source fails soft — a partial run still produces a usable report.")
    for result in sorted(results, key=lambda r: r.source):
        detail = f"{len(result.findings)} findings, {result.rows_fetched} rows fetched"
        if result.cached:
            detail += ", served from cache"
        if result.skipped_reason:
            detail += f"; skipped: {result.skipped_reason}"
        if result.errors:
            detail += f"; errors: {'; '.join(result.errors)}"
        lines.append(f"- **{result.source}** — {result.status} — {detail}")

    return "\n".join(lines) + "\n"


def write_report(markdown: str, output_dir: Path, target: Target) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = normalize(target.query).replace(" ", "-") or "target"
    path = output_dir / f"{target.mode}-{slug}-{stamp}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
