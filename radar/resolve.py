from __future__ import annotations

from datetime import datetime, timezone
from rapidfuzz import fuzz
from .db import Database, normalize_name


def queue_possible_merges(db: Database) -> int:
    entities = db.rows("SELECT id, canonical_name, normalized_name FROM entities")
    added = 0
    with db.connect() as con:
        for i, left in enumerate(entities):
            for right in entities[i+1:]:
                similarity = fuzz.token_sort_ratio(left["normalized_name"], right["normalized_name"])
                if 75 <= similarity < 90:
                    exists = con.execute("SELECT 1 FROM merge_candidates WHERE kind='entity' AND left_name=? AND right_name=? AND status='pending'",
                                         (left["canonical_name"], right["canonical_name"])).fetchone()
                    if not exists:
                        con.execute("INSERT INTO merge_candidates(kind,left_name,right_name,similarity,created_at) VALUES ('entity',?,?,?,?)",
                                    (left["canonical_name"], right["canonical_name"], similarity, datetime.now(timezone.utc).isoformat()))
                        added += 1
    return added

