from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import click

from .config import load_config
from .daily import load_query_specs, publish_daily_payload, run_daily, write_daily_payload
from .models import Target
from .report import write_reports
from .sources import SOURCES
from .runner import collect_sources


def root_path() -> Path:
    return Path.cwd()


@click.group()
@click.option("--verbose", is_flag=True)
def main(verbose):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@main.command("run")
@click.argument("company", required=False)
@click.option("--sector", help="Research a sector/keyword instead of a single company.")
@click.option("--person", help="Research a person instead of a company.")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=Path("config/config.yaml"), show_default=True)
@click.option("--sources", help="Comma-separated subset of sources to run (default: all applicable to this mode).")
@click.option("--since-days", type=int, help="Override the lookback window in days.")
@click.option("--no-cache", is_flag=True, help="Bypass the response cache and hit every source live.")
@click.option("--output", "output_dir", type=click.Path(path_type=Path), help="Override the report output directory.")
def run_cmd(company, sector, person, config_path, sources, since_days, no_cache, output_dir):
    """Run a single on-demand research pass against a target and compile a report.

    \b
    digger run "Company Name"
    digger run --sector "semiconductor packaging"
    digger run --person "Jane Chen"
    """
    given = [value for value in (company, sector, person) if value]
    if len(given) != 1:
        raise click.UsageError("Provide exactly one of: COMPANY argument, --sector, or --person.")
    if company:
        target = Target(mode="company", query=company)
    elif sector:
        target = Target(mode="sector", query=sector)
    else:
        target = Target(mode="person", query=person)

    config = load_config(config_path if config_path.exists() else None)
    if since_days:
        config["lookback_days"] = since_days

    selected = set(sources.split(",")) if sources else set(SOURCES)
    unknown = selected - set(SOURCES)
    if unknown:
        raise click.UsageError(f"Unknown source(s): {', '.join(sorted(unknown))}. Known: {', '.join(sorted(SOURCES))}")

    results = collect_sources(target, config, selected, cache_root=root_path(), use_cache=not no_cache)

    for result in sorted(results, key=lambda r: r.source):
        click.echo(f"{result.source}: {result.status} — {len(result.findings)} findings, {result.rows_fetched} rows, {len(result.errors)} errors")

    out_dir = Path(output_dir) if output_dir else root_path() / config.get("report", {}).get("output_dir", "output")
    md_path, html_path = write_reports(target, results, config, out_dir)
    click.echo(f"Report written to {md_path}")
    click.echo(f"HTML report written to {html_path}")


@main.command("list-sources")
def list_sources_cmd():
    for name, cls in sorted(SOURCES.items()):
        click.echo(f"{name:<20} modes: {', '.join(cls.modes)}")


@main.command("daily")
@click.option("--queries", "queries_path", type=click.Path(path_type=Path), default=Path("config/searches.yaml"), show_default=True)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=Path("config/config.yaml"), show_default=True)
@click.option("--output", "output_dir", type=click.Path(path_type=Path), help="Override the daily JSON output directory.")
@click.option("--include-seen", is_flag=True, help="Include previously published findings in this run.")
@click.option("--no-cache", is_flag=True, help="Bypass source response caches.")
@click.option("--no-publish", is_flag=True, help="Build and save the edition without publishing it.")
def daily_cmd(queries_path, config_path, output_dir, include_seen, no_cache, no_publish):
    """Run every configured research query, deduplicate, score, and optionally publish one daily feed."""
    if not queries_path.exists():
        raise click.UsageError(f"Queries file not found: {queries_path}. Copy config/searches.example.yaml first.")
    config = load_config(config_path if config_path.exists() else None)
    specs = load_query_specs(queries_path)
    click.echo(f"Running {len(specs)} configured intelligence searches...")
    payload = run_daily(
        specs, config, cache_root=root_path(), use_cache=not no_cache,
        include_seen=include_seen, publish=not no_publish,
    )
    configured_output = config.get("daily", {}).get("output_dir", "output/daily")
    archive, latest = write_daily_payload(payload, output_dir or root_path() / configured_output)
    click.echo(
        f"Daily feed complete — {payload['summary']['published_findings']} published findings "
        f"({payload['summary']['new_findings']} new)."
    )
    click.echo(f"Archive written to {archive}")
    click.echo(f"Latest feed written to {latest}")
    if not no_publish and config.get("daily", {}).get("publish_url"):
        click.echo("ATTENUA intelligence page updated.")


@main.command("publish")
@click.argument("feed_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=Path("config/config.yaml"), show_default=True)
@click.option("--url", help="Override daily.publish_url from configuration.")
@click.option("--token-env", help="Override daily.publish_token_env from configuration.")
@click.option("--timeout", type=float, default=60.0, show_default=True)
def publish_cmd(feed_path, config_path, url, token_env, timeout):
    """Publish a previously generated daily JSON edition."""
    config = load_config(config_path if config_path.exists() else None)
    daily_config = config.get("daily", {})
    publish_url = url or daily_config.get("publish_url")
    if not publish_url:
        raise click.UsageError("No publish URL configured; set daily.publish_url or pass --url.")
    token_name = token_env or daily_config.get("publish_token_env", "ATTENUA_INGEST_TOKEN")
    token = os.getenv(token_name, "")
    if not token:
        raise click.UsageError(f"{token_name} must be set before publishing.")
    try:
        payload = json.loads(feed_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.UsageError(f"Invalid JSON feed: {exc}") from exc
    publish_daily_payload(payload, publish_url, token, timeout=timeout)
    click.echo(f"Daily edition published from {feed_path}.")


if __name__ == "__main__":
    main()
