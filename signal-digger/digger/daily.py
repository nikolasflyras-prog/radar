from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
import yaml

from .models import Finding, Mode, Target
from .runner import collect_sources
from .sources import SOURCES
from .textutil import normalize


TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
SOURCE_WEIGHTS = {
    "sec_form_d": 28,
    "uspto_assignments": 26,
    "usaspending": 25,
    "sec_edgar": 24,
    "ftc_hsr": 24,
    "openalex": 18,
    "arxiv": 17,
    "conference_programs": 16,
    "job_boards": 15,
    "github_people": 15,
    "domain_whois": 14,
    "news_rss": 11,
    "news_gdelt": 10,
    "hackernews": 6,
}


@dataclass(frozen=True)
class QuerySpec:
    name: str
    mode: Mode
    query: str
    sources: tuple[str, ...] = ()


def load_query_specs(path: Path) -> list[QuerySpec]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = raw.get("searches") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise ValueError("queries file must contain a non-empty 'searches' list")
    specs: list[QuerySpec] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"search {index} must be a mapping")
        mode = item.get("mode", "sector")
        if mode not in ("company", "sector", "person"):
            raise ValueError(f"search {index} has invalid mode: {mode}")
        query = str(item.get("query") or "").strip()
        if not query:
            raise ValueError(f"search {index} is missing query")
        sources = tuple(item.get("sources") or ())
        unknown = set(sources) - set(SOURCES)
        if unknown:
            raise ValueError(f"search {index} has unknown sources: {', '.join(sorted(unknown))}")
        specs.append(QuerySpec(name=str(item.get("name") or query), mode=mode, query=query, sources=sources))
    return specs


def canonical_url(value: str | None) -> str:
    if not value:
        return ""
    parts = urlsplit(value)
    clean_query = urlencode([
        (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), clean_query, ""))


def finding_fingerprint(finding: Finding) -> str:
    canonical = canonical_url(finding.url)
    seed = f"url:{canonical}" if canonical else f"title:{normalize(finding.title)}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def priority_score(finding: Finding, source_count: int, generated_at: datetime) -> int:
    score = SOURCE_WEIGHTS.get(finding.source, 8)
    if finding.quiet:
        score += 22
    if finding.category == "ma_deal":
        score += 18
    elif finding.category == "people_movement":
        score += 10
    age_days = max(0, (generated_at - finding.observed_at.astimezone(timezone.utc)).days)
    score += max(0, 16 - min(16, age_days))
    score += min(16, max(0, source_count - 1) * 6)
    return min(100, score)


class DailySeenStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS daily_seen (fingerprint TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)"
        )
        self.connection.commit()

    def known(self, fingerprints: list[str]) -> set[str]:
        if not fingerprints:
            return set()
        known: set[str] = set()
        for start in range(0, len(fingerprints), 500):
            chunk = fingerprints[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = self.connection.execute(
                f"SELECT fingerprint FROM daily_seen WHERE fingerprint IN ({placeholders})", chunk
            ).fetchall()
            known.update(row[0] for row in rows)
        return known

    def mark(self, fingerprints: list[str], observed_at: datetime) -> None:
        stamp = observed_at.astimezone(timezone.utc).isoformat()
        self.connection.executemany(
            "INSERT INTO daily_seen(fingerprint, first_seen, last_seen) VALUES (?, ?, ?) "
            "ON CONFLICT(fingerprint) DO UPDATE SET last_seen=excluded.last_seen",
            [(fingerprint, stamp, stamp) for fingerprint in fingerprints],
        )
        self.connection.commit()


def build_daily_payload(
    matched: list[tuple[QuerySpec, Finding]],
    health: list[dict],
    store: DailySeenStore,
    *,
    generated_at: datetime | None = None,
    include_seen: bool = False,
    max_findings: int = 150,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc)
    merged: dict[str, dict] = {}
    for spec, finding in matched:
        fingerprint = finding_fingerprint(finding)
        item = merged.setdefault(fingerprint, {
            "id": fingerprint,
            "title": finding.title,
            "url": canonical_url(finding.url) or finding.url,
            "summary": finding.summary,
            "observed_at": finding.iso_time(),
            "category": finding.category,
            "quiet": finding.quiet,
            "quiet_reason": finding.quiet_reason,
            "sources": [],
            "searches": [],
            "entities": [],
            "people": [],
            "_finding": finding,
        })
        item["sources"] = list(dict.fromkeys([*item["sources"], finding.source]))
        item["searches"] = list(dict.fromkeys([*item["searches"], spec.name]))
        item["entities"] = list(dict.fromkeys([*item["entities"], *finding.entities]))
        item["people"] = list(dict.fromkeys([*item["people"], *finding.people]))
        if finding.quiet:
            item["quiet"] = True
            item["quiet_reason"] = item["quiet_reason"] or finding.quiet_reason
    fingerprints = list(merged)
    previously_seen = store.known(fingerprints)
    store.mark(fingerprints, generated_at)
    findings: list[dict] = []
    for fingerprint, item in merged.items():
        item["is_new"] = fingerprint not in previously_seen
        item["priority"] = priority_score(item.pop("_finding"), len(item["sources"]), generated_at)
        if include_seen or item["is_new"]:
            findings.append(item)
    findings.sort(key=lambda item: (item["priority"], item["observed_at"]), reverse=True)
    findings = findings[:max_findings]
    return {
        "schema_version": 1,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "title": "ATTENUA Daily Intelligence",
        "summary": {
            "published_findings": len(findings),
            "new_findings": sum(1 for item in findings if item["is_new"]),
            "queries": len({name for item in merged.values() for name in item["searches"]}),
            "sources_ok": sum(1 for item in health if item["status"] == "ok"),
            "sources_partial_or_failed": sum(1 for item in health if item["status"] in {"partial", "failed"}),
        },
        "findings": findings,
        "source_health": health,
    }


def write_daily_payload(payload: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(payload["generated_at"]).strftime("%Y%m%d-%H%M%S")
    archive = output_dir / f"intelligence-{stamp}.json"
    latest = output_dir / "latest.json"
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    archive.write_text(serialized, encoding="utf-8")
    latest.write_text(serialized, encoding="utf-8")
    return archive, latest


def publish_daily_payload(payload: dict, url: str, token: str, timeout: float = 60) -> None:
    response = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "SignalDigger/0.2 (daily publisher)"},
        timeout=timeout,
    )
    response.raise_for_status()


def run_daily(
    specs: list[QuerySpec],
    config: dict,
    *,
    cache_root: Path,
    use_cache: bool = True,
    include_seen: bool = False,
    publish: bool = True,
) -> dict:
    daily_config = config.get("daily", {})
    matched: list[tuple[QuerySpec, Finding]] = []
    health: list[dict] = []
    delay = max(0.0, float(daily_config.get("query_delay_seconds", 5)))
    for index, spec in enumerate(specs):
        selected = set(spec.sources) if spec.sources else set(SOURCES)
        results = collect_sources(
            Target(mode=spec.mode, query=spec.query), config, selected,
            cache_root=cache_root, use_cache=use_cache,
        )
        for result in results:
            health.append({
                "search": spec.name,
                "source": result.source,
                "status": result.status,
                "findings": len(result.findings),
                "rows": result.rows_fetched,
                "errors": result.errors,
                "skipped_reason": result.skipped_reason,
            })
            matched.extend((spec, finding) for finding in result.findings)
        if delay and index < len(specs) - 1:
            time.sleep(delay)
    store_path = cache_root / daily_config.get("state_path", "data/daily.db")
    store = DailySeenStore(store_path)
    payload = build_daily_payload(
        matched, health, store, include_seen=include_seen,
        max_findings=max(1, int(daily_config.get("max_findings", 150))),
    )
    publish_url = daily_config.get("publish_url")
    token_env = daily_config.get("publish_token_env", "ATTENUA_INGEST_TOKEN")
    if publish and publish_url:
        token = os.getenv(token_env, "")
        if not token:
            raise RuntimeError(f"{token_env} must be set when daily.publish_url is configured")
        publish_daily_payload(payload, publish_url, token)
    return payload
