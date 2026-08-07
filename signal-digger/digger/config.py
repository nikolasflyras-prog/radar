from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "contact_email": "replace-me@example.com",
    "timeout_seconds": 30,
    "rate_limit_seconds": 1.0,
    "rate_limits": {
        "www.sec.gov": 0.34,
        "data.sec.gov": 0.34,
        "efts.sec.gov": 0.34,
        "api.github.com": 1.0,
        "hn.algolia.com": 1.0,
        "www.ftc.gov": 1.0,
        "api.gdeltproject.org": 1.0,
        "rdap.org": 1.0,
    },
    "cache": {
        "path": "data/cache.db",
        "ttl_hours": {
            "default": 24,
            "sec_edgar": 12,
            "ftc_hsr": 24,
            "uspto_assignments": 168,
            "news_gdelt": 6,
            "news_rss": 6,
            "github_people": 6,
            "hackernews": 6,
            "job_boards": 12,
            "domain_whois": 168,
            "conference_programs": 720,
        },
    },
    "lookback_days": 90,
    "quiet_signals": {"correlation_window_days": 21},
    "job_boards": {"greenhouse_slugs": [], "lever_slugs": []},
    "rss_feeds": [],
    "conferences": [],
    "known_people": [],
    "tokens": {"github": None},
    "report": {"output_dir": "output"},
}


def _merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None) -> dict[str, Any]:
    cfg = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    if path and path.exists():
        with path.open("r", encoding="utf-8") as handle:
            user_cfg = yaml.safe_load(handle) or {}
        cfg = _merge(cfg, user_cfg)
    cfg["tokens"]["github"] = os.getenv("GITHUB_TOKEN", cfg["tokens"].get("github"))
    cfg["contact_email"] = os.getenv("DIGGER_CONTACT_EMAIL", cfg["contact_email"])
    return cfg


def cache_ttl_seconds(config: dict, source: str) -> float:
    hours = config.get("cache", {}).get("ttl_hours", {})
    return float(hours.get(source, hours.get("default", 24))) * 3600
