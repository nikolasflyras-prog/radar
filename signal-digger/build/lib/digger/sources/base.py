from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.robotparser import RobotFileParser

import requests

from ..cache import ResponseCache
from ..config import cache_ttl_seconds
from ..models import Finding, Mode, SourceResult, Target

LOG = logging.getLogger(__name__)

# Hosts with API-style endpoints that don't serve a meaningful robots.txt for
# programmatic query paths, or that explicitly welcome polite automated access.
NO_ROBOTS_HOSTS = {
    "data.sec.gov", "efts.sec.gov", "www.sec.gov", "api.github.com",
    "hn.algolia.com", "api.gdeltproject.org", "rdap.org",
}


class BaseSource(ABC):
    """One public data source. Subclasses implement `collect`; `run` wraps it so a
    source raising never takes the whole report down — it becomes an error on that
    source's SourceResult instead."""

    name: str = "base"
    modes: tuple[Mode, ...] = ("company", "sector", "person")

    def __init__(self, config: dict[str, Any], cache: ResponseCache | None = None, use_cache: bool = True):
        self.config = config
        self.cache = cache
        self.use_cache = use_cache and cache is not None
        self.session = requests.Session()
        contact = config.get("contact_email", "replace-me@example.com")
        self.session.headers.update({"User-Agent": f"SignalDigger/0.1.1 (research; contact={contact})"})
        self._last_request: dict[str, float] = defaultdict(float)
        self._robots: dict[str, RobotFileParser] = {}
        self.was_cached = False

    def applies_to(self, target: Target) -> bool:
        return target.mode in self.modes

    def _delay(self, url: str) -> None:
        domain = urlparse(url).netloc
        per_domain = self.config.get("rate_limits", {}).get(domain, self.config.get("rate_limit_seconds", 1.0))
        wait = float(per_domain) - (time.monotonic() - self._last_request[domain])
        if wait > 0:
            time.sleep(wait)
        self._last_request[domain] = time.monotonic()

    def _robots_ok(self, url: str) -> bool:
        domain = urlparse(url).netloc
        if domain in NO_ROBOTS_HOSTS:
            return True
        parser = self._robots.get(domain)
        if parser is None:
            robots_url = f"{urlparse(url).scheme}://{domain}/robots.txt"
            parser = RobotFileParser(robots_url)
            try:
                self._delay(robots_url)
                robots = self.session.get(robots_url, timeout=self.config.get("timeout_seconds", 30))
                robots.raise_for_status()
                parser.parse(robots.text.splitlines())
            except Exception:
                LOG.warning("Could not read robots.txt for %s; refusing broad crawl", domain)
                parser.parse(["User-agent: *", "Disallow: /"])
            parser.modified()  # marks the parser as populated; can_fetch is a no-op until this is set
            self._robots[domain] = parser
        return parser.can_fetch(self.session.headers["User-Agent"], url)

    def fetch_text(self, url: str, *, params: dict | None = None, respect_robots: bool = True,
                    method: str = "GET", ttl_seconds: float | None = None) -> str:
        """GET (or POST) `url`, transparently cached in SQLite by (source, url, params)
        for `ttl_seconds` (defaults to this source's configured TTL)."""
        ttl = cache_ttl_seconds(self.config, self.name) if ttl_seconds is None else ttl_seconds
        cache_key = f"{method} {url}?{urlencode(sorted((params or {}).items()), doseq=True)}"
        if self.use_cache:
            cached = self.cache.get(self.name, cache_key, ttl)
            if cached is not None:
                self.was_cached = True
                return cached
        if respect_robots and not self._robots_ok(url):
            raise PermissionError(f"robots.txt disallows {url}")
        self._delay(url)
        response = self.session.request(method, url, params=params, timeout=self.config.get("timeout_seconds", 30))
        response.raise_for_status()
        text = response.text
        if self.use_cache:
            self.cache.set(self.name, cache_key, text)
        return text

    def fetch_json(self, url: str, *, params: dict | None = None, respect_robots: bool = True,
                    ttl_seconds: float | None = None) -> Any:
        return json.loads(self.fetch_text(url, params=params, respect_robots=respect_robots, ttl_seconds=ttl_seconds))

    def run(self, target: Target) -> SourceResult:
        self.was_cached = False
        result = SourceResult(source=self.name)
        if not self.applies_to(target):
            result.skipped_reason = f"{self.name} does not apply to {target.mode} targets"
            return result
        try:
            result = self.collect(target)
        except Exception as exc:
            LOG.exception("Source %s failed", self.name)
            result = SourceResult(source=self.name, errors=[f"{type(exc).__name__}: {exc}"])
        result.cached = self.was_cached
        return result

    @abstractmethod
    def collect(self, target: Target) -> SourceResult: ...

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def finding(**kwargs) -> Finding:
        return Finding(**kwargs)
