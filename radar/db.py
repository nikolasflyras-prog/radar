from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .relevance import looks_like_person
from .models import CollectorResult, Signal

SCHEMA_VERSION = 1
SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_meta(version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS entities(
 id INTEGER PRIMARY KEY, canonical_name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE,
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, raw_names TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS people(
 id INTEGER PRIMARY KEY, canonical_name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE,
 last_employer TEXT, tags TEXT NOT NULL DEFAULT '[]', notes TEXT, first_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signals(
 id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, source TEXT NOT NULL,
 signal_type TEXT NOT NULL, title TEXT NOT NULL, observed_at TEXT NOT NULL,
 entity_id INTEGER REFERENCES entities(id), raw_entity_name TEXT, url TEXT, summary TEXT, raw_json TEXT NOT NULL,
 base_weight REAL, manually_entered INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signal_people(
 signal_id INTEGER NOT NULL REFERENCES signals(id), person_id INTEGER NOT NULL REFERENCES people(id),
 PRIMARY KEY(signal_id, person_id));
CREATE TABLE IF NOT EXISTS person_edges(
 person_a INTEGER NOT NULL REFERENCES people(id), person_b INTEGER NOT NULL REFERENCES people(id),
 edge_type TEXT NOT NULL, signal_id INTEGER REFERENCES signals(id), observed_at TEXT NOT NULL,
 PRIMARY KEY(person_a, person_b, edge_type, observed_at));
CREATE TABLE IF NOT EXISTS merge_candidates(
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, left_name TEXT NOT NULL, right_name TEXT NOT NULL,
 similarity REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entity_merge_log(
 id INTEGER PRIMARY KEY, surviving_entity_id INTEGER NOT NULL REFERENCES entities(id), raw_name TEXT NOT NULL,
 normalized_name TEXT NOT NULL, similarity REAL NOT NULL, created_at TEXT NOT NULL, reversed_at TEXT);
CREATE TABLE IF NOT EXISTS source_runs(
 id INTEGER PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
 rows_fetched INTEGER NOT NULL, new_signals INTEGER NOT NULL, errors_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scores(
 entity_id INTEGER PRIMARY KEY REFERENCES entities(id), score REAL NOT NULL, tier TEXT NOT NULL,
 source_count INTEGER NOT NULL, people_count INTEGER NOT NULL, calculated_at TEXT NOT NULL,
 explanation TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_signals_observed ON signals(observed_at);
CREATE INDEX IF NOT EXISTS idx_signals_entity ON signals(entity_id);
CREATE INDEX IF NOT EXISTS idx_edges_time ON person_edges(observed_at);
"""


def normalize_name(value: str) -> str:
    import re
    value = value.casefold().strip()
    value = re.sub(r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|co)\b\.?", "", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def initialize(self) -> None:
        with self.connect() as con:
            con.executescript(SCHEMA)
            row = con.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if not row:
                con.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))

    def ensure_entity(self, con: sqlite3.Connection, name: str, seen: str) -> int:
        normalized = normalize_name(name)
        row = con.execute("SELECT id, raw_names FROM entities WHERE normalized_name=?", (normalized,)).fetchone()
        if not row:
            from rapidfuzz import fuzz
            for candidate in con.execute("SELECT id, normalized_name, raw_names FROM entities"):
                similarity = fuzz.token_sort_ratio(normalized, candidate["normalized_name"])
                if similarity >= 90:
                    row = candidate
                    logged = con.execute("SELECT 1 FROM entity_merge_log WHERE surviving_entity_id=? AND normalized_name=? AND reversed_at IS NULL",
                                         (candidate["id"], normalized)).fetchone()
                    if not logged:
                        con.execute("INSERT INTO entity_merge_log(surviving_entity_id,raw_name,normalized_name,similarity,created_at) VALUES (?,?,?,?,?)",
                                    (candidate["id"], name, normalized, similarity, datetime.now(timezone.utc).isoformat()))
                    break
        if row:
            raw = set(json.loads(row["raw_names"])); raw.add(name)
            con.execute("UPDATE entities SET last_seen=?, raw_names=? WHERE id=?", (seen, json.dumps(sorted(raw)), row["id"]))
            return int(row["id"])
        cur = con.execute("INSERT INTO entities(canonical_name, normalized_name, first_seen, last_seen, raw_names) VALUES (?,?,?,?,?)",
                          (name, normalized, seen, seen, json.dumps([name])))
        return int(cur.lastrowid)

    def ensure_person(self, con: sqlite3.Connection, name: str, seen: str, **meta) -> int:
        normalized = normalize_name(name)
        row = con.execute("SELECT id FROM people WHERE normalized_name=?", (normalized,)).fetchone()
        if row:
            return int(row["id"])
        cur = con.execute("INSERT INTO people(canonical_name, normalized_name, last_employer, tags, notes, first_seen) VALUES (?,?,?,?,?,?)",
                          (name, normalized, meta.get("last_employer"), json.dumps(meta.get("tags", [])), meta.get("notes"), seen))
        return int(cur.lastrowid)

    def seed_people(self, people: list[dict]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            for person in people:
                self.ensure_person(con, person["name"], now, last_employer=person.get("last_known_employer"), tags=person.get("specialty_tags", []), notes=person.get("notes"))

    def insert_signal(self, signal: Signal) -> bool:
        observed = signal.iso_time()
        key = signal.source_key or "|".join([signal.source, signal.signal_type, signal.entity_name or "", signal.title, observed[:10]])
        fingerprint = hashlib.sha256(key.encode()).hexdigest()
        with self.connect() as con:
            entity_id = self.ensure_entity(con, signal.entity_name, observed) if signal.entity_name else None
            try:
                cur = con.execute("INSERT INTO signals(fingerprint,source,signal_type,title,observed_at,entity_id,raw_entity_name,url,summary,raw_json,base_weight,manually_entered,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (fingerprint, signal.source, signal.signal_type, signal.title, observed, entity_id, signal.entity_name, signal.url, signal.summary,
                     json.dumps(signal.raw, default=str), signal.base_weight, int(signal.manually_entered), datetime.now(timezone.utc).isoformat()))
            except sqlite3.IntegrityError:
                return False
            person_ids = [self.ensure_person(con, n, observed) for n in dict.fromkeys(signal.person_names) if looks_like_person(n)]
            for pid in person_ids:
                con.execute("INSERT OR IGNORE INTO signal_people(signal_id,person_id) VALUES (?,?)", (cur.lastrowid, pid))
            for i, left in enumerate(person_ids):
                for right in person_ids[i+1:]:
                    a, b = sorted((left, right))
                    con.execute("INSERT OR IGNORE INTO person_edges(person_a,person_b,edge_type,signal_id,observed_at) VALUES (?,?,?,?,?)",
                                (a, b, f"co_{signal.source}", cur.lastrowid, observed))
        return True

    def undo_merge(self, merge_id: int) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            merge = con.execute("SELECT * FROM entity_merge_log WHERE id=? AND reversed_at IS NULL", (merge_id,)).fetchone()
            if not merge: raise ValueError("Active merge not found")
            cur = con.execute("INSERT INTO entities(canonical_name,normalized_name,first_seen,last_seen,raw_names) VALUES (?,?,?,?,?)",
                              (merge["raw_name"], merge["normalized_name"], now, now, json.dumps([merge["raw_name"]])))
            con.execute("UPDATE signals SET entity_id=? WHERE entity_id=? AND raw_entity_name=?", (cur.lastrowid, merge["surviving_entity_id"], merge["raw_name"]))
            con.execute("UPDATE entity_merge_log SET reversed_at=? WHERE id=?", (now, merge_id))
            return int(cur.lastrowid)

    def record_run(self, result: CollectorResult, started: datetime, new_count: int) -> None:
        with self.connect() as con:
            con.execute("INSERT INTO source_runs(source,started_at,finished_at,rows_fetched,new_signals,errors_json) VALUES (?,?,?,?,?,?)",
                        (result.source, started.isoformat(), datetime.now(timezone.utc).isoformat(), result.rows_fetched, new_count, json.dumps(result.errors)))

    def rows(self, sql: str, params: tuple = ()):
        with self.connect() as con:
            return con.execute(sql, params).fetchall()
