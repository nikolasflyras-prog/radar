from pathlib import Path

import pytest
import responses

from digger.cache import ResponseCache
from digger.models import SourceResult, Target
from digger.sources.base import BaseSource


class EchoSource(BaseSource):
    name = "echo"

    def collect(self, target: Target) -> SourceResult:
        self.fetch_text("https://example.com/echo")
        return SourceResult(source=self.name, rows_fetched=1, findings=[])


def _config(tmp_path: Path) -> dict:
    return {
        "contact_email": "test@example.com", "timeout_seconds": 5, "rate_limit_seconds": 0,
        "rate_limits": {}, "cache": {"ttl_hours": {"default": 24}},
    }


@responses.activate
def test_fetch_text_caches_across_calls(tmp_path: Path):
    responses.add(responses.GET, "https://example.com/echo", body="hello", status=200)
    cache = ResponseCache(tmp_path / "cache.db")
    source = EchoSource(_config(tmp_path), cache=cache)

    first = source.fetch_text("https://example.com/echo", respect_robots=False)
    assert first == "hello"
    assert len(responses.calls) == 1

    second = source.fetch_text("https://example.com/echo", respect_robots=False)
    assert second == "hello"
    assert len(responses.calls) == 1  # served from cache, no second HTTP call
    assert source.was_cached is True


@responses.activate
def test_no_cache_hits_network_every_time(tmp_path: Path):
    responses.add(responses.GET, "https://example.com/echo", body="hello", status=200)
    responses.add(responses.GET, "https://example.com/echo", body="hello", status=200)
    cache = ResponseCache(tmp_path / "cache.db")
    source = EchoSource(_config(tmp_path), cache=cache, use_cache=False)

    source.fetch_text("https://example.com/echo", respect_robots=False)
    source.fetch_text("https://example.com/echo", respect_robots=False)
    assert len(responses.calls) == 2


@responses.activate
def test_run_wraps_exceptions_as_errors_not_crashes(tmp_path: Path):
    class BoomSource(BaseSource):
        name = "boom"

        def collect(self, target):
            raise RuntimeError("network exploded")

    source = BoomSource(_config(tmp_path), cache=ResponseCache(tmp_path / "cache.db"))
    result = source.run(Target(mode="company", query="Acme"))
    assert result.status == "failed"
    assert "network exploded" in result.errors[0]


def test_run_skips_when_mode_not_applicable(tmp_path: Path):
    class CompanyOnlySource(BaseSource):
        name = "company_only"
        modes = ("company",)

        def collect(self, target):
            raise AssertionError("collect should not be called for an inapplicable mode")

    source = CompanyOnlySource(_config(tmp_path), cache=ResponseCache(tmp_path / "cache.db"))
    result = source.run(Target(mode="person", query="Jane Chen"))
    assert result.status == "skipped"


@responses.activate
def test_robots_disallow_raises_permission_error(tmp_path: Path):
    responses.add(responses.GET, "https://blocked.example.com/robots.txt", body="User-agent: *\nDisallow: /\n", status=200)
    source = EchoSource(_config(tmp_path), cache=ResponseCache(tmp_path / "cache.db"))
    with pytest.raises(PermissionError):
        source.fetch_text("https://blocked.example.com/private", respect_robots=True)
