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


def _category(row, keywords: dict) -> str:
    raw = _raw(row)
    value = raw.get("classification")
    if value in {"spinout", "industry", "watchlist", "suppressed"}:
        return value
    if row["signal_type"] in {"spinout_discovery", "news_departure_stealth", "hn_watchlist_person", "news_watchlist_person"}:
        return "spinout"
    if row["signal_type"] in {"watchlist_public_mention", "conference_watchlist_mention", "github_identity_candidate"}:
        return "watchlist"
    if row["signal_type"] in {"industry_intelligence", "hn_keyword", "news_keyword"}:
        return classify_public_signal(f"{row['title']} {row['summary']}", keywords).category
    return "suppressed"


def _freshness(observed_at: str, half_life: float = 30) -> float:
    observed = datetime.fromisoformat(observed_at)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    age = max(0.0, (datetime.now(timezone.utc) - observed).total_seconds() / 86400)
    return math.pow(0.5, age / half_life)


def _signal_score(row, keywords: dict, spinout: bool) -> tuple[float, str]:
    raw = _raw(row)
    text = f"{row['title']} {row['summary']}"
    strong = raw.get("matched_strong_terms") or matched_terms(text, keywords.get("strong_terms", keywords.get("terms", [])))
    contextual = raw.get("matched_contextual_terms") or matched_terms(text, keywords.get("contextual_terms", []))
    startup = raw.get("startup_language") or []
    watched = raw.get("matched_watchlist_people") or []
    reasons: list[str] = []
    score = 6.0 if spinout else 2.0
    if strong:
        score += min(6, 2 * len(set(strong)))
        reasons.append("domain: " + ", ".join(strong[:4]))
    if contextual:
        score += min(3 if spinout else 2, len(set(contextual)))
    if spinout and startup:
        score += 5
        reasons.append("formation/movement: " + ", ".join(startup[:3]))
    if spinout and watched:
        score += 8
        reasons.append("watchlist: " + ", ".join(watched[:3]))
    if spinout and raw.get("own_employer_departure"):
        score += 4
        reasons.append("departure from own last-known employer: " + ", ".join(raw["own_employer_departure"][:3]))
    if spinout and raw.get("candidate_entity"):
        score += 3
        reasons.append("candidate entity: " + raw["candidate_entity"])
    if row["source"] == "hn":
        points = int(raw.get("points") or 0)
        score += 3 if points >= 50 else 2 if points >= 10 else 1 if points >= 2 else 0
    return round(score * _freshness(row["observed_at"]), 1), "; ".join(reasons) or ("spinout-classified public signal" if spinout else "semiconductor industry item")


def _rank(rows: list, keywords: dict, category: str, minimum: float, limit: int) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        if _category(row, keywords) != category:
            continue
        score, reason = _signal_score(row, keywords, category == "spinout")
        if score < minimum:
            continue
        raw = _raw(row)
        key = row["url"] or normalize_name(row["title"])
        item = {
            "source": row["source"], "signal_type": row["signal_type"], "title": row["title"],
            "observed_at": row["observed_at"], "url": row["url"], "summary": row["summary"],
            "people": row["people"], "score": score, "reason": reason,
            "candidate_entity": raw.get("candidate_entity"),
        }
        if key not in unique or score > unique[key]["score"]:
            unique[key] = item
    return sorted(unique.values(), key=lambda x: (x["score"], x["observed_at"]), reverse=True)[:limit]


def _data(db: Database, config: dict) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    week = (now - timedelta(days=7)).isoformat()
    cluster_cutoff = (now - timedelta(days=int(config.get("scoring", {}).get("cluster_window_days", 90)))).isoformat()
    display = config.get("display", {})
    keywords = config.get("keywords", {})

    leaderboard = db.rows("""SELECT e.id,e.canonical_name,e.first_seen,s.score,s.tier,s.source_count,s.people_count,s.explanation
        FROM scores s JOIN entities e ON e.id=s.entity_id WHERE s.tier!='Stored'
        ORDER BY CASE s.tier WHEN 'Investigate now' THEN 1 WHEN 'Watching' THEN 2 ELSE 3 END,s.score DESC""")
    details = {item["id"]: db.rows(
        "SELECT source,signal_type,title,observed_at,url,summary FROM signals WHERE entity_id=? ORDER BY observed_at DESC",
        (item["id"],),
    ) for item in leaderboard}

    new_entities = db.rows("""SELECT e.id,e.canonical_name,e.first_seen,s.score,s.tier,s.explanation
        FROM entities e JOIN scores s ON s.entity_id=e.id WHERE e.first_seen>=? AND s.tier!='Stored'
        ORDER BY s.score DESC LIMIT ?""", (week, int(display.get("new_entity_limit", 20))))

    recent = db.rows("""SELECT s.*,GROUP_CONCAT(DISTINCT p.canonical_name) people
        FROM signals s LEFT JOIN signal_people sp ON sp.signal_id=s.id LEFT JOIN people p ON p.id=sp.person_id
        WHERE s.observed_at>=? GROUP BY s.id ORDER BY s.observed_at DESC""", (week,))
    unresolved = [row for row in recent if row["entity_id"] is None]
    spinout_inbox = _rank(unresolved, keywords, "spinout", float(display.get("spinout_inbox_min_score", 6)), int(display.get("spinout_inbox_limit", 25)))
    industry = _rank(unresolved, keywords, "industry", float(display.get("industry_intelligence_min_score", 3)), int(display.get("industry_intelligence_limit", 15)))

    watchlist_mentions: list[dict[str, Any]] = []
    for row in recent:
        if not row["people"]:
            continue
        category = _category(row, keywords)
        if category not in {"spinout", "watchlist"} and row["signal_type"] not in {"conference_affiliation_change", "github_profile_change", "manual_note"}:
            continue
        for person in dict.fromkeys(x.strip() for x in row["people"].split(",") if x.strip()):
            watchlist_mentions.append({
                "person": person, "title": row["title"], "url": row["url"], "source": row["source"],
                "signal_type": row["signal_type"], "observed_at": row["observed_at"],
            })
    watchlist_mentions.sort(key=lambda x: x["observed_at"], reverse=True)
    watchlist_mentions = watchlist_mentions[: int(display.get("watchlist_mention_limit", 25))]

    github_candidates: list[dict[str, Any]] = []
    for row in recent:
        if row["signal_type"] != "github_identity_candidate" or not row["people"]:
            continue
        raw = _raw(row)
        github_candidates.append({
            "person": row["people"].split(",")[0], "username": raw.get("candidate_username"),
            "confidence": raw.get("confidence", 0), "reasons": raw.get("reasons", []),
            "url": row["url"], "company": raw.get("company"), "bio": raw.get("bio"),
        })
    github_candidates.sort(key=lambda x: x["confidence"], reverse=True)
    github_candidates = github_candidates[: int(display.get("github_candidate_limit", 15))]

    clusters = db.rows("""SELECT e.id,e.canonical_name,GROUP_CONCAT(DISTINCT p.canonical_name) people,
        COUNT(DISTINCT p.id) people_count,COUNT(DISTINCT s.id) signal_count,
        COUNT(DISTINCT s.source) source_count,MAX(sc.score) score
        FROM entities e JOIN signals s ON s.entity_id=e.id
        JOIN signal_people sp ON sp.signal_id=s.id JOIN people p ON p.id=sp.person_id
        LEFT JOIN scores sc ON sc.entity_id=e.id WHERE s.observed_at>=?
        GROUP BY e.id HAVING people_count>=2 AND (signal_count>=2 OR source_count>=2)
        ORDER BY COALESCE(sc.score,0) DESC,people_count DESC LIMIT 15""", (cluster_cutoff,))

    watched = {normalize_name(p["name"]): p for p in config.get("people", [])}
    qualifying = {
        "spinout_discovery", "form_d_watchlist_officer", "patent_bigco_to_new", "conference_affiliation_change",
        "github_profile_change", "github_keyword_org", "domain_hiring", "manual_note", "news_departure_stealth",
        "news_watchlist_person", "hn_watchlist_person", "watchlist_public_mention",
    }
    signal_review: list[dict[str, Any]] = []
    for row in db.rows("""SELECT p.canonical_name,p.normalized_name,COUNT(DISTINCT s.id) activity,
        GROUP_CONCAT(DISTINCT s.signal_type) reasons,MAX(s.observed_at) latest,GROUP_CONCAT(DISTINCT s.title) titles
        FROM people p JOIN signal_people sp ON sp.person_id=p.id JOIN signals s ON s.id=sp.signal_id
        WHERE s.observed_at>=? GROUP BY p.id ORDER BY activity DESC,latest DESC""", (week,)):
        types = set((row["reasons"] or "").split(","))
        if row["normalized_name"] not in watched or not types.intersection(qualifying):
            continue
        signal_review.append({"canonical_name": row["canonical_name"], "reason": (row["titles"] or row["reasons"] or "recent signal").split(",")[0]})
    signal_review = signal_review[: int(display.get("signal_review_limit", 12))]

    existing = {normalize_name(x["canonical_name"]) for x in signal_review}
    rotation = [p for p in config.get("people", []) if "prior_founder" in p.get("specialty_tags", [])] or list(config.get("people", []))
    routine_review: list[dict[str, Any]] = []
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
    health: list[dict[str, Any]] = []
    for row in db.rows("""SELECT r.* FROM source_runs r JOIN
        (SELECT source,MAX(id) id FROM source_runs GROUP BY source) x ON x.id=r.id ORDER BY source"""):
        errors = json.loads(row["errors_json"] or "[]")
        health.append({
            "source": row["source"], "rows_fetched": row["rows_fetched"], "new_signals": row["new_signals"],
            "errors": errors, "status": "Healthy" if not errors else "Partial" if row["rows_fetched"] or row["new_signals"] else "Unavailable",
        })

    return {
        "leaderboard": leaderboard, "details": details, "new_entities": new_entities,
        "spinout_inbox": spinout_inbox, "industry_intelligence": industry,
        "watchlist_mentions": watchlist_mentions, "github_candidates": github_candidates,
        "clusters": clusters, "signal_review": signal_review, "routine_review": routine_review,
        "merges": merges, "health": health,
    }


def generate(db: Database, root: Path, config: dict | None = None) -> tuple[Path, Path]:
    config = config or {}
    output = root / "output"
    output.mkdir(parents=True, exist_ok=True)
    data = _data(db, config)
    data["top"] = [x for x in data["leaderboard"] if x["tier"] == "Investigate now"]
    data["watching"] = [x for x in data["leaderboard"] if x["tier"] == "Watching"]
    data["emerging"] = [x for x in data["leaderboard"] if x["tier"] == "Discovery"]

    lines = ["# Spinout Radar — Weekly Digest", f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_", ""]
    for number, title, key in ((1, "Investigate now", "top"), (2, "Watching", "watching"), (3, "Emerging entity leads", "emerging")):
        lines.append(f"## {number}. {title}")
        items = data[key]
        if not items:
            lines.append("- None currently qualify.")
        for item in items:
            lines += [f"### {item['canonical_name']} — {item['score']:.1f}", item["explanation"] or "Cross-referenced public signals."]
            for source in data["details"][item["id"]]:
                label = f"[{source['title']}]({source['url']})" if source["url"] else source["title"]
                lines.append(f"- {label} — {source['summary']}")
            lines.append("")

    def linked(item: dict) -> str:
        return f"[{item['title']}]({item['url']})" if item.get("url") else item["title"]

    lines += ["## 4. Spinout discovery inbox", "Formation, founder-movement, or stealth signals not yet tied confidently to a scored entity."]
    lines += [f"- **{x['score']:.1f} — {linked(x)}** ({x['source']}) — {x['reason']}" for x in data["spinout_inbox"]] or ["- No qualifying spinout signals."]
    lines += ["", "## 5. Industry intelligence", "Relevant technical or market context without company-formation evidence. These are not spinout alerts."]
    lines += [f"- **{x['score']:.1f} — {linked(x)}** ({x['source']}) — {x['reason']}" for x in data["industry_intelligence"]] or ["- No qualifying industry items."]
    lines += ["", "## 6. Watchlist people mentioned publicly", "Recent public signals tied to people already on the watchlist."]
    lines += [f"- **{x['person']}** — {linked(x)} ({x['source']}, {x['signal_type']})" for x in data["watchlist_mentions"]] or ["- No watchlist people mentioned this week."]
    lines += ["", "## 7. GitHub identity candidates", "Verify each profile manually before adding it to the YAML watchlist."]
    lines += [f"- **{x['person']} → @{x['username']}** — confidence {x['confidence']}/10; {', '.join(x['reasons'])}. {x['url']} `radar confirm-github \"{x['person']}\" {x['username']}`" for x in data["github_candidates"]] or ["- No new GitHub identity candidates."]
    lines += ["", "## 8. New relevant entities this week"]
    lines += [f"- {x['canonical_name']} — {x['tier']}, {x['score']:.1f}, first seen {x['first_seen'][:10]}" for x in data["new_entities"]] or ["- None."]
    lines += ["", "## 9. Cluster watch"]
    lines += [f"- **{x['canonical_name']}** — {x['people_count']} people: {(x['people'] or '').replace(',', ', ')}; {x['signal_count']} signals across {x['source_count']} sources" for x in data["clusters"]] or ["- No corroborated multi-person clusters."]
    lines += ["", "## 10. Signal-driven LinkedIn checks", "Human review only. These names have recent public signals."]
    lines += [f"- [ ] **{x['canonical_name']}** — {x['reason']}. `radar note person \"{x['canonical_name']}\" \"observation\"`" for x in data["signal_review"]] or ["- No signal-driven profiles this week."]
    lines += ["", "## 11. Routine founder rotation", "Fallback review list, clearly separated from actual alerts."]
    lines += [f"- [ ] **{x['canonical_name']}** — {x['reason']}. `radar note person \"{x['canonical_name']}\" \"observation\"`" for x in data["routine_review"]] or ["- No routine profiles selected."]
    lines += ["", "## 12. Possible entity merges"]
    lines += [f"- {x['left_name']} ↔ {x['right_name']} ({x['similarity']:.0f}%)" for x in data["merges"]] or ["- None."]
    lines += ["", "## 13. Source health"]
    lines += [f"- {x['source']}: {x['status']}; {x['rows_fetched']} rows; {x['new_signals']} new; {len(x['errors'])} errors" for x in data["health"]] or ["- No collector runs recorded."]

    md = output / "weekly-digest.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = Environment(loader=FileSystemLoader(root / "templates"), autoescape=select_autoescape())
    template = env.get_template("digest.html.j2")
    html_path = output / "weekly-digest.html"
    html_path.write_text(template.render(generated=datetime.now(timezone.utc), **data), encoding="utf-8")
    return md, html_path
