from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
import yaml

from .models import Finding, Mode, Target
from .runner import collect_sources
from .sources import SOURCES
from .textutil import normalize


TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
TITLE_STOP_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "is", "its",
    "of", "on", "or", "the", "to", "via", "with", "new", "says", "announces", "announced",
}
AUTHORITATIVE_SOURCES = {"sec_form_d", "uspto_assignments", "usaspending", "sec_edgar", "ftc_hsr"}
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
    tokens = title_tokens(finding.title)
    seed = f"url:{canonical}" if canonical else f"event:{finding.category}:{' '.join(sorted(tokens))}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def title_tokens(value: str) -> set[str]:
    return {token for token in normalize(value).split() if len(token) > 2 and token not in TITLE_STOP_WORDS}


def title_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    return max(overlap / len(left | right), overlap / min(len(left), len(right)))


def content_hash(item: dict) -> str:
    material = "|".join([
        normalize(item["title"]),
        normalize(item.get("summary", "")),
        item.get("category", ""),
        ",".join(sorted(normalize(value) for value in item.get("entities", []))),
        ",".join(sorted(normalize(value) for value in item.get("people", []))),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def confidence_score(sources: list[str]) -> int:
    source_set = set(sources)
    score = 50 + min(24, max(0, len(source_set) - 1) * 8)
    if source_set & AUTHORITATIVE_SOURCES:
        score += 20
    return min(98, score)


def why_it_matters(item: dict) -> str:
    if item.get("quiet"):
        return "A primary or low-visibility source surfaced this before broad news coverage, making it useful as an early signal."
    if item.get("category") == "ma_deal":
        return "Financing and transaction activity can reveal strategic priorities, competitive positioning, and changes in industry structure."
    if item.get("category") == "people_movement":
        return "Senior technical and executive movement can foreshadow new products, company formation, or a change in strategic direction."
    if set(item.get("sources", [])) & {"arxiv", "openalex"}:
        return "The work may indicate where technical capability and commercialization activity are developing before they appear in company announcements."
    return "This development adds evidence about where semiconductor technology, capital, or commercial demand is moving."


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
    # Corroboration improves confidence, but syndicated coverage should not
    # overwhelm a quieter primary-source signal.
    score += min(10, max(0, source_count - 1) * 4)
    return min(100, score)


@dataclass(frozen=True)
class SeenEvent:
    first_seen: str
    last_seen: str
    content_hash: str
    sources: tuple[str, ...]
    occurrence_count: int


class DailySeenStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS daily_seen (fingerprint TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS daily_events ("
            "fingerprint TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, "
            "content_hash TEXT NOT NULL, sources_json TEXT NOT NULL, occurrence_count INTEGER NOT NULL DEFAULT 1)"
        )
        self.connection.commit()

    def states(self, fingerprints: list[str]) -> dict[str, SeenEvent]:
        if not fingerprints:
            return {}
        states: dict[str, SeenEvent] = {}
        for start in range(0, len(fingerprints), 500):
            chunk = fingerprints[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = self.connection.execute(
                "SELECT fingerprint, first_seen, last_seen, content_hash, sources_json, occurrence_count "
                f"FROM daily_events WHERE fingerprint IN ({placeholders})", chunk
            ).fetchall()
            for fingerprint, first_seen, last_seen, digest, sources_json, occurrences in rows:
                states[fingerprint] = SeenEvent(
                    first_seen=first_seen,
                    last_seen=last_seen,
                    content_hash=digest,
                    sources=tuple(json.loads(sources_json or "[]")),
                    occurrence_count=int(occurrences),
                )
        return states

    def mark(self, items: list[dict], observed_at: datetime) -> None:
        stamp = observed_at.astimezone(timezone.utc).isoformat()
        self.connection.executemany(
            "INSERT INTO daily_events(fingerprint, first_seen, last_seen, content_hash, sources_json, occurrence_count) "
            "VALUES (?, ?, ?, ?, ?, 1) ON CONFLICT(fingerprint) DO UPDATE SET "
            "last_seen=excluded.last_seen, content_hash=excluded.content_hash, sources_json=excluded.sources_json, "
            "occurrence_count=daily_events.occurrence_count + 1",
            [
                (item["id"], stamp, stamp, item["content_hash"], json.dumps(item["sources"]))
                for item in items
            ],
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
        tokens = title_tokens(finding.title)
        observed = datetime.fromisoformat(finding.iso_time())
        canonical = canonical_url(finding.url)

        # Exact URLs/source IDs are handled by the fingerprint. For syndicated
        # or lightly rewritten coverage, join near-identical titles into the
        # same event when the category and timing also agree.
        if fingerprint not in merged:
            for candidate_id, candidate in merged.items():
                if candidate["category"] != finding.category:
                    continue
                if abs((observed - candidate["_observed"]).days) > 7:
                    continue
                similarity = title_similarity(tokens, candidate["_tokens"])
                shared_entities = bool(set(map(normalize, finding.entities)) & set(map(normalize, candidate["entities"])))
                if similarity >= 0.84 or (shared_entities and similarity >= 0.66):
                    fingerprint = candidate_id
                    break
        item = merged.setdefault(fingerprint, {
            "id": fingerprint,
            "title": finding.title,
            "url": canonical or finding.url,
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
            "_tokens": tokens,
            "_observed": observed,
        })
        item["sources"] = list(dict.fromkeys([*item["sources"], finding.source]))
        item["searches"] = list(dict.fromkeys([*item["searches"], spec.name]))
        item["entities"] = list(dict.fromkeys([*item["entities"], *finding.entities]))
        item["people"] = list(dict.fromkeys([*item["people"], *finding.people]))
        if finding.quiet:
            item["quiet"] = True
            item["quiet_reason"] = item["quiet_reason"] or finding.quiet_reason
    fingerprints = list(merged)
    previous = store.states(fingerprints)
    findings: list[dict] = []
    for fingerprint, item in merged.items():
        state = previous.get(fingerprint)
        item["content_hash"] = content_hash(item)
        if state is None:
            status = "new"
            first_seen = generated_at
            occurrences = 1
        else:
            last_seen = datetime.fromisoformat(state.last_seen)
            if generated_at - last_seen >= timedelta(days=30):
                status = "resurfaced"
            elif state.content_hash != item["content_hash"]:
                status = "updated"
            elif set(item["sources"]) - set(state.sources):
                status = "corroborated"
            else:
                status = "ongoing"
            first_seen = datetime.fromisoformat(state.first_seen)
            occurrences = state.occurrence_count + 1
        item["status"] = status
        item["is_new"] = status == "new"
        item["first_seen"] = first_seen.astimezone(timezone.utc).isoformat()
        item["last_seen"] = generated_at.astimezone(timezone.utc).isoformat()
        item["occurrence_count"] = occurrences
        item["confidence"] = confidence_score(item["sources"])
        item["why_it_matters"] = why_it_matters(item)
        item["priority"] = priority_score(item.pop("_finding"), len(item["sources"]), generated_at)
        item.pop("_tokens", None)
        item.pop("_observed", None)
        if include_seen or status != "ongoing":
            findings.append(item)
    store.mark(list(merged.values()), generated_at)
    findings.sort(key=lambda item: (item["priority"], item["observed_at"]), reverse=True)
    findings = findings[:max_findings]
    status_counts = {
        status: sum(1 for item in merged.values() if item.get("status") == status)
        for status in ("new", "updated", "corroborated", "ongoing", "resurfaced")
    }
    return {
        "schema_version": 2,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "title": "ATTENUA Daily Intelligence",
        "summary": {
            "published_findings": len(findings),
            "new_findings": status_counts["new"],
            "published_events": len(findings),
            "new_events": status_counts["new"],
            "updated_events": status_counts["updated"],
            "corroborated_events": status_counts["corroborated"],
            "ongoing_events": status_counts["ongoing"],
            "resurfaced_events": status_counts["resurfaced"],
            "duplicate_observations": max(0, len(matched) - len(merged)),
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
