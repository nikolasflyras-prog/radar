from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click

from .cache import ResponseCache
from .config import load_config
from .models import SourceResult, Target
from .report import write_reports
from .sources import SOURCES


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

    cache = ResponseCache(root_path() / config.get("cache", {}).get("path", "data/cache.db"))
    instances = [cls(config, cache=cache, use_cache=not no_cache) for name, cls in SOURCES.items() if name in selected]

    results: list[SourceResult] = []
    with ThreadPoolExecutor(max_workers=min(8, len(instances) or 1)) as pool:
        futures = {pool.submit(source.run, target): source.name for source in instances}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # belt & suspenders — BaseSource.run already catches
                results.append(SourceResult(source=name, errors=[f"{type(exc).__name__}: {exc}"]))

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


if __name__ == "__main__":
    main()
