from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from .db import Database


DEFAULT_WEIGHTS = {
    "patent_bigco_to_new": 40,
    "form_d_watchlist_officer": 35,
    "form_d_keyword_issuer": 20,
    "form_d_discovery": 8,
    "conference_affiliation_change": 25,
    "github_keyword_org": 20,
    "github_activity_drop": 10,
    "domain_hiring": 15,
    "domain_registered": 5,
    "new_incorporation_keyword": 5,
    "news_departure_stealth": 10,
    "spinout_discovery": 12,
    "industry_intelligence": 0,
    "hn_watchlist_person": 8,
    "manual_note": 30,
    "github_profile_change": 10,
    "conference_affiliation_observation": 3,
    "hn_keyword": 3,
    "news_keyword": 3,
}


def score_all(db: Database, config: dict) -> None:
    now = datetime.now(timezone.utc)
    scoring = config.get("scoring", {})
    half_life = float(scoring.get("half_life_days", 60))
    weights = DEFAULT_WEIGHTS | scoring.get("weights", {})
    signals = db.rows("""SELECT s.*, e.id entity_id, e.canonical_name,
        GROUP_CONCAT(sp.person_id) person_ids FROM signals s LEFT JOIN entities e ON e.id=s.entity_id
        LEFT JOIN signal_people sp ON sp.signal_id=s.id GROUP BY s.id""")
    by_entity = defaultdict(list)
    for row in signals:
        if row["entity_id"]:
            by_entity[row["entity_id"]].append(row)
    prior_founders = {r["id"] for r in db.rows("SELECT id FROM people WHERE tags LIKE '%prior_founder%'")}
    investigate = float(scoring.get("investigate_threshold", 60))
    watching = float(scoring.get("watching_threshold", 25))
    discovery = float(scoring.get("discovery_threshold", 8))
    with db.connect() as con:
        con.execute("DELETE FROM scores")
        for entity_id, rows in by_entity.items():
            raw = 0.0
            sources: set[str] = set()
            people: set[int] = set()
            phrases: list[str] = []
            for row in rows:
                observed = datetime.fromisoformat(row["observed_at"])
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                age = max(0.0, (now - observed).total_seconds() / 86400)
                weight = float(row["base_weight"] if row["base_weight"] is not None else weights.get(row["signal_type"], 1))
                ids = {int(x) for x in (row["person_ids"] or "").split(",") if x}
                if ids & prior_founders:
                    weight *= 1.5
                raw += weight * math.pow(0.5, age / half_life)
                sources.add(row["source"])
                people |= ids
                if row["title"] not in phrases:
                    phrases.append(row["title"])
            score = raw * (1 + 0.5 * max(0, len(sources) - 1))
            if len(people) >= 3 and len(rows) >= 2:
                score *= 1.5
            tier = (
                "Investigate now" if score >= investigate else
                "Watching" if score >= watching else
                "Discovery" if score >= discovery else
                "Stored"
            )
            con.execute(
                "INSERT INTO scores(entity_id,score,tier,source_count,people_count,calculated_at,explanation) VALUES (?,?,?,?,?,?,?)",
                (entity_id, round(score, 1), tier, len(sources), len(people), now.isoformat(), "; ".join(phrases[:5])),
            )
