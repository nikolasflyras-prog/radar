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
    "conference_watchlist_mention": 4,
    "github_keyword_org": 20,
    "github_activity_drop": 10,
    "github_identity_candidate": 2,
    "domain_hiring": 15,
    "domain_registered": 5,
    "new_incorporation_keyword": 5,
    "news_departure_stealth": 20,
    "news_watchlist_person": 14,
    "watchlist_public_mention": 4,
    "spinout_discovery": 12,
    "industry_intelligence": 0,
    "hn_watchlist_person": 8,
    "manual_note": 30,
    "github_profile_change": 10,
    "conference_affiliation_observation": 3,
    "hn_keyword": 3,
    "news_keyword": 3,
}

# A company cannot reach Watching or Investigate-now on generic corroboration alone.
# At least one formation, fundraising, founder-movement, or watchlist-change signal is required.
FORMATION_INTENT_TYPES = {
    "patent_bigco_to_new",
    "form_d_watchlist_officer",
    "form_d_keyword_issuer",
    "conference_affiliation_change",
    "github_keyword_org",
    "github_profile_change",
    "new_incorporation_keyword",
    "news_departure_stealth",
    "news_watchlist_person",
    "spinout_discovery",
    "hn_watchlist_person",
    "manual_note",
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
            source_values: dict[str, list[float]] = defaultdict(list)
            sources: set[str] = set()
            people: set[int] = set()
            phrases: list[str] = []
            intent_present = False

            for row in rows:
                observed = datetime.fromisoformat(row["observed_at"])
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                age = max(0.0, (now - observed).total_seconds() / 86400)
                weight = float(row["base_weight"] if row["base_weight"] is not None else weights.get(row["signal_type"], 1))
                ids = {int(x) for x in (row["person_ids"] or "").split(",") if x}
                if ids & prior_founders:
                    weight *= 1.5
                value = weight * math.pow(0.5, age / half_life)
                if value > 0:
                    source_values[row["source"]].append(value)
                    sources.add(row["source"])
                people |= ids
                intent_present = intent_present or row["signal_type"] in FORMATION_INTENT_TYPES
                if row["title"] not in phrases:
                    phrases.append(row["title"])

            # Repeated articles/domains from one collector are correlated evidence. Count the
            # strongest result in full and only 25% of the next two from the same source.
            raw = 0.0
            for values in source_values.values():
                ranked = sorted(values, reverse=True)
                raw += ranked[0] + 0.25 * sum(ranked[1:3])

            # Independent source types still increase confidence, but more conservatively than v0.5.
            score = raw * (1 + 0.35 * max(0, len(sources) - 1))
            if intent_present and len(people) >= 3 and len(rows) >= 2:
                score *= 1.25

            tier = (
                "Investigate now" if score >= investigate else
                "Watching" if score >= watching else
                "Discovery" if score >= discovery else
                "Stored"
            )
            if not intent_present and tier in {"Investigate now", "Watching"}:
                tier = "Discovery"

            con.execute(
                "INSERT INTO scores(entity_id,score,tier,source_count,people_count,calculated_at,explanation) VALUES (?,?,?,?,?,?,?)",
                (entity_id, round(score, 1), tier, len(sources), len(people), now.isoformat(), "; ".join(phrases[:5])),
            )
