from pathlib import Path

from digger.cache import ResponseCache


def test_miss_then_hit(tmp_path: Path):
    cache = ResponseCache(tmp_path / "cache.db")
    assert cache.get("src", "key1", ttl_seconds=60) is None
    cache.set("src", "key1", "body-value")
    assert cache.get("src", "key1", ttl_seconds=60) == "body-value"


def test_ttl_zero_never_hits(tmp_path: Path):
    cache = ResponseCache(tmp_path / "cache.db")
    cache.set("src", "key1", "body-value")
    assert cache.get("src", "key1", ttl_seconds=0) is None


def test_different_sources_are_isolated(tmp_path: Path):
    cache = ResponseCache(tmp_path / "cache.db")
    cache.set("source_a", "same-key", "a-body")
    cache.set("source_b", "same-key", "b-body")
    assert cache.get("source_a", "same-key", ttl_seconds=60) == "a-body"
    assert cache.get("source_b", "same-key", ttl_seconds=60) == "b-body"


def test_expired_entry_is_purged(tmp_path: Path):
    import sqlite3
    from datetime import datetime, timedelta, timezone

    cache = ResponseCache(tmp_path / "cache.db")
    cache.set("src", "old", "stale-body")
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    con = sqlite3.connect(cache.path)
    con.execute("UPDATE response_cache SET fetched_at=? WHERE source='src'", (old_time,))
    con.commit()
    con.close()
    assert cache.get("src", "old", ttl_seconds=3600) is None
    removed = cache.purge_expired(max_age_seconds=3600)
    assert removed == 1
