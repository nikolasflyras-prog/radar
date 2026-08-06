from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from .db import Database


DEFAULT_WEIGHTS = {
    "patent_bigco_to_new": 40, "form_d_watchlist_officer": 35, "form_d_keyword_issuer": 25,
    "conference_affiliation_change": 25, "github_keyword_org": 20, "github_activity_drop": 10,
    "domain_hiring": 15, "domain_registered": 5, "new_incorporation_keyword": 5,
    "news_departure_stealth": 10, "manual_note": 30, "github_profile_change": 10,
    "conference_affiliation_observation": 3, "hn_keyword": 2, "news_keyword": 2,
}


def _components(edges, nodes):
    graph = defaultdict(set)
    for row in edges: graph[row["person_a"]].add(row["person_b"]); graph[row["person_b"]].add(row["person_a"])
    seen = set(); out = []
    for node in nodes:
        if node in seen: continue
        todo = [node]; comp = set()
        while todo:
            current = todo.pop()
            if current in seen: continue
            seen.add(current); comp.add(current); todo.extend(graph[current] - seen)
        out.append(comp)
    return out


def score_all(db: Database, config: dict) -> None:
    now = datetime.now(timezone.utc)
    half_life = float(config.get("scoring", {}).get("half_life_days", 60))
    weights = DEFAULT_WEIGHTS | config.get("scoring", {}).get("weights", {})
    signals = db.rows("""SELECT s.*, e.id entity_id, e.canonical_name,
        GROUP_CONCAT(sp.person_id) person_ids FROM signals s LEFT JOIN entities e ON e.id=s.entity_id
        LEFT JOIN signal_people sp ON sp.signal_id=s.id GROUP BY s.id""")
    by_entity = defaultdict(list)
    for row in signals:
        if row["entity_id"]: by_entity[row["entity_id"]].append(row)
    cutoff = (now - timedelta(days=int(config.get("scoring", {}).get("cluster_window_days", 90)))).isoformat()
    edges = db.rows("SELECT * FROM person_edges WHERE observed_at>=?", (cutoff,))
    nodes = {x for e in edges for x in (e["person_a"], e["person_b"])}
    large_cluster_people = set().union(*(c for c in _components(edges, nodes) if len(c) >= 3)) if nodes else set()
    prior_founders = {r["id"] for r in db.rows("SELECT id FROM people WHERE tags LIKE '%prior_founder%'")}
    with db.connect() as con:
        con.execute("DELETE FROM scores")
        for entity_id, rows in by_entity.items():
            raw = 0.0; sources = set(); people = set(); phrases = []
            for row in rows:
                age = max(0.0, (now - datetime.fromisoformat(row["observed_at"])).total_seconds()/86400)
                weight = row["base_weight"] if row["base_weight"] is not None else weights.get(row["signal_type"], 1)
                ids = {int(x) for x in (row["person_ids"] or "").split(",") if x}
                if ids & prior_founders: weight *= 1.5
                raw += weight * math.pow(0.5, age / half_life)
                sources.add(row["source"]); people |= ids; phrases.append(row["title"])
            score = raw * (1 + 0.5*(len(sources)-1))
            if len(people & large_cluster_people) >= 3: score *= 2
            investigate = float(config.get("scoring", {}).get("investigate_threshold", 60))
            watching = float(config.get("scoring", {}).get("watching_threshold", 30))
            tier = "Investigate now" if score >= investigate else "Watching" if score >= watching else "Stored"
            con.execute("INSERT INTO scores(entity_id,score,tier,source_count,people_count,calculated_at,explanation) VALUES (?,?,?,?,?,?,?)",
                        (entity_id, round(score,1), tier, len(sources), len(people), now.isoformat(), "; ".join(phrases[:5])))

