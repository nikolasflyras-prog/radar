from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS response_cache(
 source TEXT NOT NULL, cache_key TEXT NOT NULL, key_text TEXT NOT NULL,
 fetched_at TEXT NOT NULL, body TEXT NOT NULL,
 PRIMARY KEY(source, cache_key));
"""


def _digest(key_text: str) -> str:
    return hashlib.sha256(key_text.encode("utf-8")).hexdigest()


class ResponseCache:
    """Caches raw source responses in SQLite so a re-run on the same target within
    a source's TTL doesn't re-hit the network. Stores the raw body only; parsing
    always happens fresh from the cached (or freshly fetched) body."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Sources run concurrently in threads and share this cache; a generous busy
        # timeout lets a writer wait out another connection instead of raising
        # "database is locked" under normal fan-out contention.
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.executescript(SCHEMA)
            yield con
            con.commit()
        finally:
            con.close()

    def get(self, source: str, key_text: str, ttl_seconds: float) -> str | None:
        if ttl_seconds <= 0:
            return None
        with self._connect() as con:
            row = con.execute(
                "SELECT fetched_at, body FROM response_cache WHERE source=? AND cache_key=?",
                (source, _digest(key_text)),
            ).fetchone()
        if not row:
            return None
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        return row["body"] if age <= ttl_seconds else None

    def set(self, source: str, key_text: str, body: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO response_cache(source, cache_key, key_text, fetched_at, body) "
                "VALUES (?,?,?,?,?)",
                (source, _digest(key_text), key_text, datetime.now(timezone.utc).isoformat(), body),
            )

    def purge_expired(self, max_age_seconds: float) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_seconds
        with self._connect() as con:
            cur = con.execute(
                "DELETE FROM response_cache WHERE fetched_at < ?",
                (datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat(),),
            )
            return cur.rowcount
