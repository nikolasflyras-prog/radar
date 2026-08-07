from __future__ import annotations

import html as html_lib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def all_findings(results: list[SourceResult]) -> list[Finding]:
    findings: list[Finding] = []
    for result in results:
        findings.extend(result.findings)
    return findings


def _date(finding: Finding) -> str:
    return finding.observed_at.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _link(finding: Finding) -> str:
    return f"[{finding.title}]({finding.url})" if finding.url else finding.title


def _finding_line(finding: Finding) -> str:
    who = f"; people: {', '.join(finding.people)}" if finding.people else ""
    summary = f" — {finding.summary}" if finding.summary else ""
    return f"- **{_date(finding)}** — {_link(finding)} — _{finding.source}_{who}{summary}"


def build_report_context(target: Target, results: list[SourceResult], config: dict) -> dict[str, Any]:
    """Dedupe findings, run the quiet-signal correlation once, and bucket everything
    by category — the shared computation behind both the Markdown and HTML
    renderers, so they never disagree on what's quiet or how things sort."""
    findings = dedupe(all_findings(results))
    window_days = int(config.get("quiet_signals", {}).get("correlation_window_days", 21))
    correlate_quiet(findings, window_days)
    return {
        "quiet": newest_first([f for f in findings if f.quiet]),
        "categories": {cat: newest_first([f for f in findings if f.category == cat]) for cat in CATEGORY_TITLES},
        "results": sorted(results, key=lambda r: r.source),
        "generated": datetime.now(timezone.utc),
    }


def render_markdown_report(target: Target, ctx: dict[str, Any]) -> str:
    lines = [
        f"# Signal Digger Report: {target.query}",
        f"_Mode: {target.mode} · Generated {ctx['generated']:%Y-%m-%d %H:%M UTC}_",
        "",
        "## Quiet signals worth a second look",
        "Findings that don't fit neatly elsewhere, or arrived with no matching news coverage nearby.",
    ]
    quiet = ctx["quiet"]
    if quiet:
        lines += [f"- **{_date(f)}** — {_link(f)} — _{f.source}_ — {f.quiet_reason or 'flagged quiet'}" for f in quiet]
    else:
        lines.append("- None this run.")
    lines.append("")

    for category, title in CATEGORY_TITLES.items():
        items = ctx["categories"][category]
        lines.append(f"## {title}")
        lines += [_finding_line(f) for f in items] if items else ["- No findings this run."]
        lines.append("")

    lines.append("## Source Run Health")
    lines.append("Every source fails soft — a partial run still produces a usable report.")
    for result in ctx["results"]:
        detail = f"{len(result.findings)} findings, {result.rows_fetched} rows fetched"
        if result.cached:
            detail += ", served from cache"
        if result.skipped_reason:
            detail += f"; skipped: {result.skipped_reason}"
        if result.errors:
            detail += f"; errors: {'; '.join(result.errors)}"
        lines.append(f"- **{result.source}** — {result.status} — {detail}")

    return "\n".join(lines) + "\n"


def compile_report(target: Target, results: list[SourceResult], config: dict) -> str:
    return render_markdown_report(target, build_report_context(target, results, config))


HTML_STYLE = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 880px;
  margin: 2.5rem auto; padding: 0 1.25rem; line-height: 1.5; color: #1a1a1a; background: #fdfdfc; }
h1 { font-size: 1.5rem; margin-bottom: 0.15rem; }
.meta { color: #666; font-size: 0.9rem; margin-bottom: 2rem; }
h2 { font-size: 1.05rem; text-transform: uppercase; letter-spacing: 0.03em; color: #444;
  border-bottom: 1px solid #e2e2e0; padding-bottom: 0.4rem; margin-top: 2.25rem; }
.section-note { color: #777; font-size: 0.85rem; margin: 0.25rem 0 1rem; }
ul.findings { list-style: none; padding: 0; margin: 0; }
ul.findings li { padding: 0.6rem 0; border-bottom: 1px solid #f0f0ee; }
ul.findings li:last-child { border-bottom: none; }
.date { display: inline-block; font-variant-numeric: tabular-nums; color: #666; font-size: 0.85rem;
  min-width: 5.5rem; }
.tag { display: inline-block; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.03em;
  color: #555; background: #eee; border-radius: 3px; padding: 0.05rem 0.4rem; margin-left: 0.4rem; }
.summary { display: block; color: #555; font-size: 0.9rem; margin-top: 0.15rem; }
.empty { color: #888; font-style: italic; }
a { color: #0b5fae; text-decoration: none; }
a:hover { text-decoration: underline; }
#quiet { background: #fff8e6; border: 1px solid #f0dca0; border-radius: 8px; padding: 0.5rem 1.25rem 1.1rem; }
#quiet h2 { border-bottom-color: #f0dca0; color: #6b5400; }
#quiet .quiet-reason { color: #7a5f00; font-size: 0.85rem; display: block; margin-top: 0.15rem; }
table.health { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
table.health th, table.health td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; }
.status { border-radius: 3px; padding: 0.05rem 0.5rem; font-size: 0.78rem; font-weight: 600; }
.status-ok { background: #dff5e1; color: #206a2c; }
.status-partial { background: #fdecc8; color: #8a5a00; }
.status-failed { background: #fbdede; color: #9a2b2b; }
.status-skipped { background: #eee; color: #666; }
.errors { color: #9a2b2b; font-size: 0.82rem; }
@media (prefers-color-scheme: dark) {
  body { color: #e8e6e1; background: #16171a; }
  .meta, .section-note, .date, .summary { color: #9a9a95; }
  h2 { color: #cfcfc9; border-bottom-color: #2c2d31; }
  ul.findings li { border-bottom-color: #232428; }
  .tag { background: #26272b; color: #c8c8c2; }
  a { color: #6cb2ff; }
  #quiet { background: #2a2408; border-color: #4a3f10; }
  #quiet h2 { border-bottom-color: #4a3f10; color: #e8cf6a; }
  #quiet .quiet-reason { color: #d8bd55; }
  table.health th, table.health td { border-bottom-color: #232428; }
  .status-ok { background: #163b1f; color: #7ee096; }
  .status-partial { background: #4a3a0a; color: #f0c766; }
  .status-failed { background: #4a1616; color: #f29999; }
  .status-skipped { background: #26272b; color: #a3a39d; }
  .errors { color: #f29999; }
}
"""


def _esc(value: str) -> str:
    return html_lib.escape(str(value), quote=True)


def _html_finding_item(finding: Finding, *, with_reason: bool = False) -> str:
    label = f'<a href="{_esc(finding.url)}">{_esc(finding.title)}</a>' if finding.url else _esc(finding.title)
    who = f" &middot; people: {_esc(', '.join(finding.people))}" if finding.people else ""
    summary_text = finding.quiet_reason if with_reason else finding.summary
    summary_html = f'<span class="{"quiet-reason" if with_reason else "summary"}">{_esc(summary_text)}</span>' if summary_text else ""
    return (
        f"<li><span class=\"date\">{_date(finding)}</span> {label}"
        f"<span class=\"tag\">{_esc(finding.source)}</span>{who}{summary_html}</li>"
    )


def _html_findings_list(findings: list[Finding], *, empty_text: str, with_reason: bool = False) -> str:
    if not findings:
        return f'<p class="empty">{_esc(empty_text)}</p>'
    items = "\n".join(_html_finding_item(f, with_reason=with_reason) for f in findings)
    return f'<ul class="findings">\n{items}\n</ul>'


def render_html_report(target: Target, ctx: dict[str, Any]) -> str:
    quiet_html = _html_findings_list(ctx["quiet"], empty_text="None this run.", with_reason=True)
    category_sections = []
    for category, title in CATEGORY_TITLES.items():
        items_html = _html_findings_list(ctx["categories"][category], empty_text="No findings this run.")
        category_sections.append(f"<section><h2>{_esc(title)}</h2>{items_html}</section>")

    health_rows = []
    for result in ctx["results"]:
        detail_bits = [f"{len(result.findings)} findings", f"{result.rows_fetched} rows fetched"]
        if result.cached:
            detail_bits.append("served from cache")
        detail = ", ".join(detail_bits)
        note = ""
        if result.skipped_reason:
            note = f'<div class="errors">skipped: {_esc(result.skipped_reason)}</div>'
        elif result.errors:
            note = f'<div class="errors">{_esc("; ".join(result.errors))}</div>'
        health_rows.append(
            f"<tr><td>{_esc(result.source)}</td>"
            f'<td><span class="status status-{_esc(result.status)}">{_esc(result.status)}</span></td>'
            f"<td>{_esc(detail)}{note}</td></tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signal Digger: {_esc(target.query)}</title>
<style>{HTML_STYLE}</style>
</head>
<body>
<h1>Signal Digger Report: {_esc(target.query)}</h1>
<p class="meta">Mode: {_esc(target.mode)} &middot; Generated {ctx['generated']:%Y-%m-%d %H:%M UTC}</p>

<section id="quiet">
<h2>Quiet signals worth a second look</h2>
<p class="section-note">Findings that don't fit neatly elsewhere, or arrived with no matching news coverage nearby.</p>
{quiet_html}
</section>

{"".join(category_sections)}

<section>
<h2>Source Run Health</h2>
<p class="section-note">Every source fails soft — a partial run still produces a usable report.</p>
<table class="health">
<thead><tr><th>Source</th><th>Status</th><th>Detail</th></tr></thead>
<tbody>
{"".join(health_rows)}
</tbody>
</table>
</section>
</body>
</html>
"""


def _report_path(output_dir: Path, target: Target, stamp: str, extension: str) -> Path:
    slug = normalize(target.query).replace(" ", "-") or "target"
    return output_dir / f"{target.mode}-{slug}-{stamp}.{extension}"


def write_report(markdown: str, output_dir: Path, target: Target, stamp: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = _report_path(output_dir, target, stamp, "md")
    path.write_text(markdown, encoding="utf-8")
    return path


def write_html_report(html_text: str, output_dir: Path, target: Target, stamp: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = _report_path(output_dir, target, stamp, "html")
    path.write_text(html_text, encoding="utf-8")
    return path


def write_reports(target: Target, results: list[SourceResult], config: dict, output_dir: Path) -> tuple[Path, Path]:
    """Compile and write both the Markdown and HTML reports for one run, sharing a
    single timestamp so the two files are obviously a pair."""
    ctx = build_report_context(target, results, config)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    md_path = write_report(render_markdown_report(target, ctx), output_dir, target, stamp=stamp)
    html_path = write_html_report(render_html_report(target, ctx), output_dir, target, stamp=stamp)
    return md_path, html_path
