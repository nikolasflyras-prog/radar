from pathlib import Path

from digger.config import cache_ttl_seconds, load_config


def test_defaults_without_a_config_file(tmp_path: Path):
    cfg = load_config(tmp_path / "does-not-exist.yaml")
    assert cfg["contact_email"] == "replace-me@example.com"
    assert cfg["lookback_days"] == 90
    assert "sec_edgar" in cfg["cache"]["ttl_hours"]
    assert cfg["rate_limits"]["api.gdeltproject.org"] == 10.0
    assert cfg["daily"]["query_delay_seconds"] == 15


def test_user_config_merges_over_defaults(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("contact_email: me@example.com\ncache:\n  ttl_hours:\n    sec_edgar: 1\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg["contact_email"] == "me@example.com"
    assert cfg["cache"]["ttl_hours"]["sec_edgar"] == 1
    # Untouched defaults survive the merge.
    assert cfg["cache"]["ttl_hours"]["default"] == 24
    assert cfg["rate_limit_seconds"] == 1.0


def test_cache_ttl_seconds_falls_back_to_default(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert cache_ttl_seconds(cfg, "unknown_source") == 24 * 3600
    assert cache_ttl_seconds(cfg, "sec_edgar") == 12 * 3600
