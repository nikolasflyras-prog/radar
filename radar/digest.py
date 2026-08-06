from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from .db import Database


def _data(db: Database):
    leaderboard = db.rows("""SELECT e.id,e.canonical_name,e.first_seen,s.score,s.tier,s.source_count,s.people_count,s.explanation
        FROM scores s JOIN entities e ON e.id=s.entity_id WHERE s.tier!='Stored' ORDER BY s.score DESC""")
    details = {}
    for item in leaderboard:
        details[item["id"]] = db.rows("SELECT source,signal_type,title,observed_at,url,summary FROM signals WHERE entity_id=? ORDER BY observed_at DESC", (item["id"],))
    week = (datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
    new_items = db.rows("SELECT canonical_name,first_seen FROM entities WHERE first_seen>=? ORDER BY first_seen DESC", (week,))
    manual = db.rows("""SELECT p.canonical_name, COUNT(*) activity, GROUP_CONCAT(DISTINCT s.signal_type) reasons
        FROM people p JOIN signal_people sp ON sp.person_id=p.id JOIN signals s ON s.id=sp.signal_id
        WHERE s.observed_at>=? GROUP BY p.id ORDER BY activity DESC LIMIT 15""", (week,))
    edges = db.rows("""SELECT pa.canonical_name a,pb.canonical_name b,pe.edge_type,pe.observed_at
        FROM person_edges pe JOIN people pa ON pa.id=pe.person_a JOIN people pb ON pb.id=pe.person_b
        WHERE pe.observed_at>=? ORDER BY pe.observed_at DESC LIMIT 50""", ((datetime.now(timezone.utc)-timedelta(days=90)).isoformat(),))
    merges = db.rows("SELECT * FROM merge_candidates WHERE status='pending' ORDER BY similarity DESC")
    health = db.rows("""SELECT r.* FROM source_runs r JOIN (SELECT source,MAX(id) id FROM source_runs GROUP BY source) x ON x.id=r.id ORDER BY source""")
    return leaderboard, details, new_items, manual, edges, merges, health


def generate(db: Database, root: Path) -> tuple[Path, Path]:
    output = root / "output"; output.mkdir(parents=True, exist_ok=True)
    leaderboard, details, new_items, manual, edges, merges, health = _data(db)
    lines = ["# Spinout Radar — Weekly Digest", f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_", "", "## 1. Top alerts"]
    top = [x for x in leaderboard if x["tier"] == "Investigate now"]
    if not top: lines.append("No entities crossed the investigate-now threshold this week.")
    for item in top:
        lines += [f"### {item['canonical_name']} — {item['score']:.1f}", item["explanation"] or "Cross-referenced public signals.", "", "Sources:"]
        for s in details[item["id"]]: lines.append(f"- [{s['title']}]({s['url']}) — {s['summary']}" if s["url"] else f"- {s['title']} — {s['summary']}")
        lines += ["", "**Suggested action:** Review the people, patents, filing, and domain; seek a warm-path introduction.", ""]
    lines += ["## 2. New this week"] + ([f"- {x['canonical_name']} — first seen {x['first_seen'][:10]}" for x in new_items] or ["- None."])
    lines += ["", "## 3. Cluster watch"] + ([f"- {x['a']} ↔ {x['b']} ({x['edge_type']})" for x in edges] or ["- No recent connected-person edges."])
    lines += ["", "## 4. Manual LinkedIn review sheet", "Use LinkedIn manually; this system never accesses it."]
    lines += ([f"- [ ] Check {x['canonical_name']} — {x['reasons']}; look for title/company change. Feed back with `radar note person \"{x['canonical_name']}\" \"observation\"`." for x in manual] or ["- No profiles prioritized this week."])
    lines += ["", "## 5. Possible entity merges"] + ([f"- {x['left_name']} ↔ {x['right_name']} ({x['similarity']:.0f}%)" for x in merges] or ["- None."])
    lines += ["", "## 6. Source health"] + ([f"- {x['source']}: {x['rows_fetched']} rows, {x['new_signals']} new signals, errors: {x['errors_json']}" for x in health] or ["- No collector runs recorded."])
    md = output / "weekly-digest.md"; md.write_text("\n".join(lines)+"\n", encoding="utf-8")
    env = Environment(loader=FileSystemLoader(root / "templates"), autoescape=select_autoescape())
    template = env.get_template("digest.html.j2")
    html_path = output / "weekly-digest.html"
    html_path.write_text(template.render(generated=datetime.now(timezone.utc), leaderboard=leaderboard, details=details,
        new_items=new_items, manual=manual, edges=edges, merges=merges, health=health), encoding="utf-8")
    return md, html_path

