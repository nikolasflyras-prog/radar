from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .db import Database, normalize_name
from .relevance import classify_public_signal, matched_terms


def _raw(row) -> dict:
    try:
        return json.loads(row["raw_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _row_category(row, keyword_cfg: dict) -> str:
    raw = _raw(row)
    category = raw.get("classification")
    if category in {"spinout", "industry", "suppressed"}:
        return category
    if row["signal_type"] in {"spinout_discovery", "news_departure_stealth", "hn_watchlist_person"}:
        return "spinout"
    if row["signal_type"] in {"industry_intelligence", "hn_keyword", "news_keyword"}:
        return classify_public_signal(f"{row['title']} {row['summary']}", keyword_cfg).category
    return "suppressed"


def _spinout_score(row, keyword_cfg: dict) -> tuple[float, list[str]]:
    raw = _raw(row)
    reasons: list[str] = []
    score = 6.0
    strong = raw.get("matched_strong_terms") or matched_terms(
        f"{row['title']} {row['summary']}", keyword_cfg.get("strong_terms", keyword_cfg.get("terms", []))
    )
    contextual = raw.get("matched_contextual_terms") or matched_terms(
        f"{row['title']} {row['summary']}", keyword_cfg.get("contextual_terms", [])
    )
    startup = raw.get("startup_language") or []
    watched = raw.get("matched_watchlist_people") or []
    candidate = raw.get("candidate_entity")
    if strong:
        score += min(6, 2 * len(set(strong)))
        reasons.append("strong domain: " + ", ".join(strong[:4]))
    if contextual:
        score += min(3, len(set(contextual)))
    if startup:
        score += 5
        reasons.append("formation/departure language: " + ", ".join(startup[:3]))
    if watched:
        score += 8
        reasons.append("watchlist person: " + ", ".join(watched[:3]))
    if candidate:
        score += 3
        reasons.append("candidate entity: " + candidate)
    if row["source"] == "hn":
        points = int(raw.get("points") or 0)
        if points >= 50:
            score += 3
        elif points >= 10:
            score += 2
        elif points >= 2:
            score += 1
    age_days = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(row["observed_at"])).total_seconds() / 86400)
    score *= math.pow(0.5, age_days / 30)
    return round(score, 1), reasons or ["spinout-classified public signal"]


def _industry_score(row, keyword_cfg: dict) -> tuple[float, list[str]]:
    raw = _raw(row)
    reasons: list[str] = []
    strong = raw.get("matched_strong_terms") or matched_terms(
        f"{row['title']} {row['summary']}", keyword_cfg.get("strong_terms", keyword_cfg.get("terms", []))
    )
    contextual = raw.get("matched_contextual_terms") or matched_terms(
        f"{row['title']} {row['summary']}", keyword_cfg.get("contextual_terms", [])
    )
    score = 2.0 + min(6, 2 * len(set(strong))) + min(2, len(set(contextual)))
    if strong:
        reasons.append("domain: " + ", ".join(strong[:4]))
    elif contextual:
        reasons.append("context: " + ", ".join(contextual[:4]))
    if row["source"] == "hn":
        points = int(raw.get("points") or 0)
        if points >= 50:
            score += 3
        elif points >= 10:
            score += 2
        elif points >= 2:
            score += 1
    age_days = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(row["observed_at"])).total_seconds() / 86400)
    score *= math.pow(0.5, age_days / 30)
    return round(score, 1), reasons or ["semiconductor industry item"]


def _dedupe_rank(rows: list, keyword_cfg: dict, category: str, minimum: float, limit: int) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        if _row_category(row, keyword_cfg) != category:
            continue
        score, reasons = (_spinout_score(row, keyword_cfg) if category == "spinout" else _industry_score(row, keyword_cfg))
        if score < minimum:
            continue
        raw = _raw(row)
        key = row["url"] or normalize_name(row["title"])
        item = {
            "source": row["source"], "signal_type": row["signal_type"], "title": row["title"],
            "observed_at": row["observed_at"], "url": row["url"], "summary": row["summary"],
            "people": row["people"], "score": score, "reason": "; ".join(reasons),
            "candidate_entity": raw.get("candidate_entity"),
        }
        if key not in by_key or score > by_key[key]["score"]:
            by_key[key] = item
    return sorted(by_key.values(), key=lambda x: (x["score"], x["observed_at"]), reverse=True)[:limit]


def _data(db: Database, config: dict):
    now = datetime.now(timezone.utc)
    week = (now - timedelta(days=7)).isoformat()
    cluster_cutoff = (now - timedelta(days=int(config.get("scoring", {}).get("cluster_window_days", 90)))).isoformat()
    display = config.get("display", {})
    keyword_cfg = config.get("keywords", {})

    leaderboard = db.rows("""SELECT e.id,e.canonical_name,e.first_seen,s.score,s.tier,s.source_count,s.people_count,s.explanation
        FROM scores s JOIN entities e ON e.id=s.entity_id WHERE s.tier!='Stored'
        ORDER BY CASE s.tier WHEN 'Investigate now' THEN 1 WHEN 'Watching' THEN 2 ELSE 3 END, s.score DESC""")
    details: dict[int, list] = {}
    for item in leaderboard:
        details[item["id"]] = db.rows(
            "SELECT source,signal_type,title,observed_at,url,summary FROM signals WHERE entity_id=? ORDER BY observed_at DESC",
            (item["id"],),
        )

    new_entities = db.rows("""SELECT e.id,e.canonical_name,e.first_seen,s.score,s.tier,s.explanation
        FROM entities e JOIN scores s ON s.entity_id=e.id
        WHERE e.first_seen>=? AND s.tier!='Stored' ORDER BY s.score DESC LIMIT ?""",
        (week, int(display.get("new_entity_limit", 20))),
    )

    unresolved = db.rows("""SELECT s.*, GROUP_CONCAT(DISTINCT p.canonical_name) people
        FROM signals s LEFT JOIN signal_people sp ON sp.signal_id=s.id LEFT JOIN people p ON p.id=sp.person_id
        WHERE s.entity_id IS NULL AND s.observed_at>=?
        GROUP BY s.id ORDER BY s.observed_at DESC""", (week,))
    spinout_inbox = _dedupe_rank(
        unresolved, keyword_cfg, "spinout",
        float(display.get("spinout_inbox_min_score", 6)),
        int(display.get("spinout_inbox_limit", 20)),
    )
    industry_intelligence = _dedupe_rank(
        unresolved, keyword_cfg, "industry",
        float(display.get("industry_intelligence_min_score", 3)),
        int(display.get("industry_intelligence_limit", 15)),
    )

    clusters = db.rows("""SELECT e.id,e.canonical_name,
        GROUP_CONCAT(DISTINCT p.canonical_name) people,
        COUNT(DISTINCT p.id) people_count,COUNT(DISTINCT s.id) signal_count,
        COUNT(DISTINCT s.source) source_count,MAX(sc.score) score
        FROM entities e JOIN signals s ON s.entity_id=e.id
        JOIN signal_people sp ON sp.signal_id=s.id JOIN people p ON p.id=sp.person_id
        LEFT JOIN scores sc ON sc.entity_id=e.id
        WHERE s.observed_at>=?
        GROUP BY e.id HAVING people_count>=2 AND (signal_count>=2 OR source_count>=2)
        ORDER BY COALESCE(sc.score,0) DESC, people_count DESC LIMIT 15""", (cluster_cutoff,))

    watched_names = {normalize_name(p["name"]) for p in config.get("people", [])}
    signal_review = []
    qualifying_types = {
        "spinout_discovery", "form_d_watchlist_officer", "patent_bigco_to_new",
        "conference_affiliation_change", "github_profile_change", "github_keyword_org",
        "domain_hiring", "manual_note", "news_departure_stealth", "hn_watchlist_person",
    }
    for row in db.rows("""SELECT p.canonical_name,p.normalized_name,COUNT(DISTINCT s.id) activity,
        GROUP_CONCAT(DISTINCT s.signal_type) reasons,MAX(s.observed_at) latest,
        GROUP_CONCAT(DISTINCT s.title) titles
        FROM people p JOIN signal_people sp ON sp.person_id=p.id JOIN signals s ON s.id=sp.signal_id
        WHERE s.observed_at>=? GROUP BY p.id ORDER BY activity DESC,latest DESC""", (week,)):
        signal_types = set((row["reasons"] or "").split(","))
        if row["normalized_name"] not in watched_names or not signal_types.intersection(qualifying_types):
            continue
        signal_review.append({
            "canonical_name": row["canonical_name"],
            "reason": (row["titles"] or row["reasons"] or "recent signal").split(",")[0],
            "activity": row["activity"],
        })
    signal_review = signal_review[: int(display.get("signal_review_limit", 10))]

    existing = {normalize_name(x["canonical_name"]) for x in signal_review}
    routine_review = []
    rotation = [p for p in config.get("people", []) if "prior_founder" in p.get("specialty_tags", [])]
    if not rotation:
        rotation = list(config.get("people", []))
    routine_limit = int(display.get("routine_review_limit", 5))
    if rotation:
        offset = (now.isocalendar().week * max(1, routine_limit)) % len(rotation)
        for person in rotation[offset:] + rotation[:offset]:
            if normalize_name(person["name"]) in existing:
                continue
            routine_review.append({
                "canonical_name": person["name"],
                "reason": f"routine prior-founder rotation; last known at {person.get('last_known_employer') or 'unknown employer'}",
            })
            if len(routine_review) >= routine_limit:
                break

    merges = db.rows("SELECT * FROM merge_candidates WHERE status='pending' ORDER BY similarity DESC")
    health_rows = db.rows("""SELECT r.* FROM source_runs r JOIN
        (SELECT source,MAX(id) id FROM source_runs GROUP BY source) x ON x.id=r.id ORDER BY source""")
    health = []
    for row in health_rows:
        errors = json.loads(row["errors_json"] or "[]")
        health.append({
            "source": row["source"], "rows_fetched": row["rows_fetched"], "new_signals": row["new_signals"],
            "errors": errors, "status": "Healthy" if not errors else "Partial" if row["rows_fetched"] or row["new_signals"] else "Unavailable",
        })
    return (
        leaderboard, details, new_entities, spinout_inbox, industry_intelligence,
        clusters, signal_review, routine_review, merges, health,
    )


def generate(db: Database, root: Path, config: dict | None = None) -> tuple[Path, Path]:
    config = config or {}
    output = root / "output"
    output.mkdir(parents=True, exist_ok=True)
    (
        leaderboard, details, new_entities, spinout_inbox, industry_intelligence,
        clusters, signal_review, routine_review, merges, health,
    ) = _data(db, config)
    top = [x for x in leaderboard if x["tier"] == "Investigate now"]
    watching = [x for x in leaderboard if x["tier"] == "Watching"]
    emerging = [x for x in leaderboard if x["tier"] == "Discovery"]

    lines = ["# Spinout Radar — Weekly Digest", f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_", ""]
    sections = [("1. Investigate now", top), ("2. Watching", watching), ("3. Emerging entity leads", emerging)]
    for heading, items in sections:
        lines.append(f"## {heading}")
        if not items:
            lines.append("- None currently qualify.")
        for item in items:
            lines += [f"### {item['canonical_name']} — {item['score']:.1f}", item["explanation"] or "Cross-referenced public signals."]
            for s in details[item["id"]]:
                source = f"[{s['title']}]({s['url']})" if s["url"] else s["title"]
                lines.append(f"- {source} — {s['summary']}")
            lines.append("")

    lines += ["## 4. Spinout discovery inbox", "Formation, founder-movement, or stealth signals not yet tied confidently to a scored entity."]
    lines += [f"- **{x['score']:.1f} — [{x['title']}]({x['url']})** ({x['source']}) — {x['reason']}" if x["url"] else f"- **{x['score']:.1f} — {x['title']}** ({x['source']}) — {x['reason']}" for x in spinout_inbox] or ["- No qualifying spinout signals."]
    lines += ["", "## 5. Industry intelligence", "Relevant technical or market items without formation evidence. Useful context, not spinout alerts."]
    lines += [f"- **{x['score']:.1f} — [{x['title']}]({x['url']})** ({x['source']}) — {x['reason']}" if x["url"] else f"- **{x['score']:.1f} — {x['title']}** ({x['source']}) — {x['reason']}" for x in industry_intelligence] or ["- No qualifying industry items."]
    lines += ["", "## 6. New relevant entities this week"]
    lines += [f"- {x['canonical_name']} — {x['tier']}, {x['score']:.1f}, first seen {x['first_seen'][:10]}" for x in new_entities] or ["- None."]
    lines += ["", "## 7. Cluster watch"]
    lines += [f"- **{x['canonical_name']}** — {x['people_count']} people: {(x['people'] or '').replace(',', ', ')}; {x['signal_count']} signals across {x['source_count']} sources" for x in clusters] or ["- No corroborated multi-person clusters."]
    lines += ["", "## 8. Signal-driven LinkedIn checks", "Human review only. These names have recent public signals."]
    lines += [f"- [ ] **{x['canonical_name']}** — {x['reason']}. `radar note person \"{x['canonical_name']}\" \"observation\"`" for x in signal_review] or ["- No signal-driven profiles this week."]
    lines += ["", "## 9. Routine founder rotation", "Fallback review list, clearly separated from actual alerts."]
    lines += [f"- [ ] **{x['canonical_name']}** — {x['reason']}. `radar note person \"{x['canonical_name']}\" \"observation\"`" for x in routine_review] or ["- No routine profiles selected."]
    lines += ["", "## 10. Possible entity merges"] + ([f"- {x['left_name']} ↔ {x['right_name']} ({x['similarity']:.0f}%)" for x in merges] or ["- None."])
    lines += ["", "## 11. Source health"] + ([f"- {x['source']}: {x['status']}; {x['rows_fetched']} rows; {x['new_signals']} new; {len(x['errors'])} errors" for x in health] or ["- No collector runs recorded."])
    md = output / "weekly-digest.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    env = Environment(loader=FileSystemLoader(root / "templates"), autoescape=select_autoescape())
    template = env.get_template("digest.html.j2")
    html_path = output / "weekly-digest.html"
    html_path.write_text(template.render(
        generated=datetime.now(timezone.utc), top=top, watching=watching, emerging=emerging,
        details=details, spinout_inbox=spinout_inbox, industry_intelligence=industry_intelligence,
        new_entities=new_entities, clusters=clusters, signal_review=signal_review,
        routine_review=routine_review, merges=merges, health=health,
    ), encoding="utf-8")
    return md, html_path
