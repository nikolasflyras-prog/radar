from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import requests

from ..models import CollectorResult

LOG = logging.getLogger(__name__)


class BaseCollector(ABC):
    name = "base"

    def __init__(self, config: dict, db=None):
        self.config, self.db = config, db
        self.session = requests.Session()
        contact = config.get("contact_email", "replace-me@example.com")
        self.session.headers.update({"User-Agent": f"SpinoutRadar/0.5 research-contact={contact}"})
        self._last_request = defaultdict(float)
        self._robots: dict[str, RobotFileParser] = {}

    def _delay(self, url: str) -> None:
        domain = urlparse(url).netloc
        per_domain = self.config.get("rate_limits", {}).get(domain, self.config.get("rate_limit_seconds", 1.0))
        wait = float(per_domain) - (time.monotonic() - self._last_request[domain])
        if wait > 0: time.sleep(wait)
        self._last_request[domain] = time.monotonic()

    def get(self, url: str, *, respect_robots: bool = True, **kwargs) -> requests.Response:
        domain = urlparse(url).netloc
        if respect_robots and domain not in {"data.sec.gov", "www.sec.gov", "api.github.com", "hn.algolia.com"}:
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
                self._robots[domain] = parser
            if parser.mtime() and not parser.can_fetch(self.session.headers["User-Agent"], url):
                raise PermissionError(f"robots.txt disallows {url}")
        self._delay(url)
        response = self.session.get(url, timeout=self.config.get("timeout_seconds", 30), **kwargs)
        response.raise_for_status()
        return response

    def result(self, since: datetime | None = None) -> CollectorResult:
        try:
            return self.collect(since)
        except Exception as exc:
            LOG.exception("Collector %s failed", self.name)
            return CollectorResult(source=self.name, errors=[f"{type(exc).__name__}: {exc}"])

    @abstractmethod
    def collect(self, since: datetime | None = None) -> CollectorResult: ...

    @staticmethod
    def utcnow() -> datetime: return datetime.now(timezone.utc)
