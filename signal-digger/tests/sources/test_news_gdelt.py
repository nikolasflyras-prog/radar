import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import responses

from digger.cache import ResponseCache
from digger.models import Target
from digger.sources.news_gdelt import NewsGdeltSource, build_queries, parse_observed


def test_parse_observed_parses_gdelt_timestamp():
    observed = parse_observed("20260301T120000Z", datetime.now(timezone.utc))
    assert observed.year == 2026 and observed.month == 3 and observed.day == 1


def test_parse_observed_falls_back_on_bad_input():
    fallback = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert parse_observed(None, fallback) == fallback
    assert parse_observed("not-a-date", fallback) == fallback


def test_build_queries_quotes_multiword_ma_terms_and_sanitizes_target():
    ma_query, general_query = build_queries(Target(mode="sector", query='semiconductor "packaging"'))

    assert general_query == '"semiconductor packaging"'
    assert '"to merge"' in ma_query
    assert '"definitive agreement"' in ma_query
    assert '("acquire" OR "acquires"' in ma_query


@responses.activate
def test_collect_classifies_ma_and_general_articles(tmp_path):
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    seendate = recent.strftime("%Y%m%dT%H%M%SZ")
    ma_payload = {"articles": [
        {"title": "Acme to acquire Widgets Co", "url": "https://news.example.com/1", "domain": "news.example.com",
         "seendate": seendate, "snippet": "definitive agreement announced"},
    ]}
    general_payload = {"articles": [
        {"title": "Acme launches new product", "url": "https://news.example.com/2", "domain": "news.example.com",
         "seendate": seendate, "snippet": "no deal language here"},
    ]}
    responses.add(responses.GET, "https://api.gdeltproject.org/api/v2/doc/doc", body=json.dumps(ma_payload), status=200)
    responses.add(responses.GET, "https://api.gdeltproject.org/api/v2/doc/doc", body=json.dumps(general_payload), status=200)

    config = {"contact_email": "t@example.com", "timeout_seconds": 5, "rate_limit_seconds": 0, "rate_limits": {},
              "cache": {"ttl_hours": {"default": 0}}, "lookback_days": 90,
              "news_search": {"records_per_query": 75, "gdelt_retry_attempts": 0}}
    source = NewsGdeltSource(config, cache=ResponseCache(tmp_path / "cache.db"), use_cache=False)
    result = source.collect(Target(mode="company", query="Acme"))

    categories = {f.title: f.category for f in result.findings}
    assert categories["Acme to acquire Widgets Co"] == "ma_deal"
    assert categories["Acme launches new product"] == "general_signal"


@responses.activate
def test_collect_reports_error_without_crashing(tmp_path):
    responses.add(responses.GET, "https://api.gdeltproject.org/api/v2/doc/doc", status=500)
    config = {"contact_email": "t@example.com", "timeout_seconds": 5, "rate_limit_seconds": 0, "rate_limits": {},
              "cache": {"ttl_hours": {"default": 0}}, "lookback_days": 90,
              "news_search": {"records_per_query": 75, "gdelt_retry_attempts": 0}}
    source = NewsGdeltSource(config, cache=ResponseCache(tmp_path / "cache.db"), use_cache=False)
    result = source.collect(Target(mode="company", query="Acme"))
    assert result.errors
    assert result.findings == []


@responses.activate
def test_collect_preserves_plain_text_gdelt_error_detail(tmp_path):
    responses.add(
        responses.GET, "https://api.gdeltproject.org/api/v2/doc/doc",
        body="Invalid query: phrases must be surrounded by quotes", status=200,
    )
    config = {"contact_email": "t@example.com", "timeout_seconds": 5, "rate_limit_seconds": 0, "rate_limits": {},
              "cache": {"ttl_hours": {"default": 0}}, "lookback_days": 90, "news_search": {"records_per_query": 75}}
    source = NewsGdeltSource(config, cache=ResponseCache(tmp_path / "cache.db"), use_cache=False)

    result = source.collect(Target(mode="sector", query="semiconductor packaging"))

    assert len(result.errors) == 2
    assert all("phrases must be surrounded by quotes" in error for error in result.errors)


@responses.activate
def test_search_retries_a_429_then_succeeds(tmp_path):
    responses.add(
        responses.GET, "https://api.gdeltproject.org/api/v2/doc/doc",
        body="rate limited", status=429, headers={"Retry-After": "0"},
    )
    responses.add(
        responses.GET, "https://api.gdeltproject.org/api/v2/doc/doc",
        json={"articles": []}, status=200,
    )
    config = {"contact_email": "t@example.com", "timeout_seconds": 5, "rate_limit_seconds": 0, "rate_limits": {},
              "cache": {"ttl_hours": {"default": 0}}, "news_search": {"gdelt_retry_attempts": 1, "gdelt_retry_backoff_seconds": 0}}
    source = NewsGdeltSource(config, cache=ResponseCache(tmp_path / "cache.db"), use_cache=False)

    with mock.patch("time.sleep") as sleeper:
        assert source._search('"Acme"', 30, 10) == []

    assert len(responses.calls) == 2
    sleeper.assert_called_once_with(0.0)
