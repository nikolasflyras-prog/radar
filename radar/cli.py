from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
import click
import yaml

from .collectors import COLLECTORS
from .config import load_config
from .db import Database
from .digest import generate
from .models import Signal
from .resolve import queue_possible_merges
from .score import score_all


def root_path() -> Path: return Path.cwd()
def context():
    root = root_path(); cfg = load_config(root); db = Database(root / cfg.get("database", "data/radar.db")); return root, cfg, db

@click.group()
@click.option("--verbose", is_flag=True)
def main(verbose):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

@main.command("init")
def init_cmd():
    root, cfg, db = context(); db.initialize(); db.seed_people(cfg.get("people", []))
    click.echo(f"Initialized {db.path}")

@main.command("run")
@click.option("--source", type=click.Choice(sorted(COLLECTORS)))
@click.option("--since-days", type=int)
def run_cmd(source, since_days):
    root, cfg, db = context(); db.initialize(); db.seed_people(cfg.get("people", []))
    since = datetime.now(timezone.utc)-timedelta(days=since_days) if since_days else None
    names = [source] if source else list(COLLECTORS)
    failures = 0
    for name in names:
        started = datetime.now(timezone.utc); result = COLLECTORS[name](cfg, db).result(since)
        new = sum(db.insert_signal(s) for s in result.signals); db.record_run(result, started, new)
        failures += bool(result.errors); click.echo(f"{name}: {result.rows_fetched} rows, {new} new, {len(result.errors)} errors")
    queue_possible_merges(db); score_all(db, cfg); md, html = generate(db, root, cfg)
    click.echo(f"Digest: {md} and {html}")
    if failures > int(cfg.get("max_collector_failures", 2)): raise click.ClickException(f"{failures} collectors reported errors")

@main.command("digest")
@click.option("--regenerate", is_flag=True, help="Accepted for an explicit regeneration workflow.")
def digest_cmd(regenerate):
    root,cfg,db=context(); db.initialize(); score_all(db,cfg); md,html=generate(db,root,cfg); click.echo(f"Generated {md} and {html}")

@main.command("add-person")
@click.argument("name")
@click.option("--employer")
@click.option("--github", "github_names", multiple=True)
def add_person(name, employer, github_names):
    path=root_path()/"config/watchlist_people.yaml"; data=yaml.safe_load(path.read_text()) or {"people":[]}
    data.setdefault("people",[]).append({"name":name,"known_aliases":[],"github_usernames":list(github_names),"last_known_employer":employer,"specialty_tags":[],"notes":""})
    path.write_text(yaml.safe_dump(data,sort_keys=False),encoding="utf-8"); click.echo(f"Added {name}")

@main.command("add-org")
@click.argument("name")
@click.option("--aliases", multiple=True)
def add_org(name, aliases):
    path=root_path()/"config/watchlist_orgs.yaml"; data=yaml.safe_load(path.read_text()) or {"organizations":[]}
    data.setdefault("organizations",[]).append({"name":name,"aliases":list(aliases)})
    path.write_text(yaml.safe_dump(data,sort_keys=False),encoding="utf-8"); click.echo(f"Added {name}")

@main.command("note")
@click.argument("kind", type=click.Choice(["person","entity"]))
@click.argument("name")
@click.argument("observation")
def note(kind,name,observation):
    root,cfg,db=context(); db.initialize(); sig=Signal(source="manual",signal_type="manual_note",title=f"Manual observation: {name}",
        observed_at=datetime.now(timezone.utc),person_names=[name] if kind=="person" else [],entity_name=name if kind=="entity" else f"People cluster: {name}",
        summary=observation,raw={"kind":kind,"name":name},base_weight=30,manually_entered=True)
    db.insert_signal(sig); click.echo("Observation recorded")

@main.command("backfill")
@click.option("--source", required=True, type=click.Choice(["uspto","edgar","hn","gdelt","rss","googlenews"]))
@click.option("--months", default=6, type=click.IntRange(1,36))
def backfill(source, months):
    ctx=click.get_current_context(); ctx.invoke(run_cmd, source=source, since_days=months*30)

@main.command("top")
@click.option("--limit", default=20)
def top(limit):
    root,cfg,db=context(); db.initialize(); score_all(db,cfg)
    rows=db.rows("SELECT e.canonical_name,s.score,s.tier FROM scores s JOIN entities e ON e.id=s.entity_id ORDER BY score DESC LIMIT ?",(limit,))
    for row in rows: click.echo(f"{row['score']:6.1f}  {row['tier']:<15} {row['canonical_name']}")


@main.command("confirm-github")
@click.argument("name")
@click.argument("username")
def confirm_github(name, username):
    path = root_path() / "config/watchlist_people.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {"people": []}
    from .db import normalize_name
    target = normalize_name(name)
    for person in data.get("people", []):
        if normalize_name(person.get("name", "")) != target:
            continue
        handles = person.setdefault("github_usernames", [])
        if username not in handles:
            handles.append(username)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        click.echo(f"Confirmed @{username} for {person['name']}")
        return
    raise click.ClickException(f"Watchlist person not found: {name}")

@main.command("github-candidates")
@click.option("--limit", default=20, type=click.IntRange(1, 100))
def github_candidates(limit):
    root, cfg, db = context(); db.initialize()
    rows = db.rows("""SELECT s.title,s.url,s.summary,s.raw_json,p.canonical_name person
        FROM signals s JOIN signal_people sp ON sp.signal_id=s.id JOIN people p ON p.id=sp.person_id
        WHERE s.signal_type='github_identity_candidate' ORDER BY s.observed_at DESC LIMIT ?""", (limit,))
    if not rows:
        click.echo("No GitHub identity candidates stored. Run `radar run --source github`.")
        return
    import json
    for row in rows:
        raw = json.loads(row["raw_json"] or "{}")
        click.echo(f"{raw.get('confidence', 0):>2}/10  {row['person']} -> @{raw.get('candidate_username')}  {row['url']}")

@main.command("undo-merge")
@click.argument("merge_id", type=int)
def undo_merge(merge_id):
    root,cfg,db=context(); db.initialize()
    try: entity_id = db.undo_merge(merge_id)
    except ValueError as exc: raise click.ClickException(str(exc)) from exc
    click.echo(f"Reversed merge {merge_id}; restored entity {entity_id}")

@main.command("reset-data")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def reset_data(yes):
    root, cfg, db = context()
    if db.path.exists():
        if not yes and not click.confirm(f"Back up and reset {db.path}?"):
            raise click.Abort()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = db.path.with_name(f"radar-backup-{stamp}.db")
        shutil.copy2(db.path, backup)
        db.path.unlink()
        click.echo(f"Reset {db.path}; backup saved to {backup}")
    else:
        click.echo(f"No database found at {db.path}; creating a new one")
    db.initialize(); db.seed_people(cfg.get("people", []))

@main.command("stats")
def stats():
    root, cfg, db = context(); db.initialize()
    click.echo("Signals by source/type:")
    rows = db.rows("SELECT source,signal_type,COUNT(*) n,SUM(CASE WHEN entity_id IS NULL THEN 1 ELSE 0 END) unresolved FROM signals GROUP BY source,signal_type ORDER BY n DESC")
    if not rows:
        click.echo("  No signals stored.")
    for row in rows:
        click.echo(f"  {row['source']:<12} {row['signal_type']:<30} {row['n']:>5} total  {row['unresolved']:>5} unresolved")
    click.echo(f"Named entities: {db.rows('SELECT COUNT(*) n FROM entities')[0]['n']}")
    click.echo(f"Watchlist/people rows: {db.rows('SELECT COUNT(*) n FROM people')[0]['n']}")

if __name__ == "__main__": main()
