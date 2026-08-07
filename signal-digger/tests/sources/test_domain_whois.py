from datetime import datetime, timedelta, timezone
from unittest import mock

import responses

from digger.cache import ResponseCache
from digger.models import Target
from digger.sources.domain_whois import DomainWhoisSource, classify_event, domain_candidates, rdap_event_date


def _config():
    return {
        "contact_email": "t@example.com", "timeout_seconds": 5, "rate_limit_seconds": 0, "rate_limits": {},
        "cache": {"ttl_hours": {"default": 0}}, "domain_whois": {"recent_registration_days": 365},
    }


def _fake_getaddrinfo(host, *args, **kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def test_domain_candidates_strips_punctuation_and_applies_suffixes():
    candidates = domain_candidates("Acme, Inc.", suffixes=(".com", ".io"))
    assert candidates == ["acmeinc.com", "acmeinc.io"]


def test_domain_candidates_too_short_returns_empty():
    assert domain_candidates("A!", suffixes=(".com",)) == []


def test_rdap_event_date_finds_named_event():
    events = [
        {"eventAction": "registration", "eventDate": "2026-01-15T00:00:00Z"},
        {"eventAction": "last changed", "eventDate": "2026-02-01T00:00:00Z"},
    ]
    registered = rdap_event_date(events, "registration")
    changed = rdap_event_date(events, "last changed")
    assert registered.year == 2026 and registered.month == 1
    assert changed.month == 2


def test_rdap_event_date_missing_event_returns_none():
    assert rdap_event_date([{"eventAction": "expiration", "eventDate": "2030-01-01T00:00:00Z"}], "registration") is None


def test_classify_event_registration_only():
    assert classify_event(is_recent_registration=True, is_recent_change=False) == "registration"


def test_classify_event_change_only():
    assert classify_event(is_recent_registration=False, is_recent_change=True) == "change"


def test_classify_event_both_recent():
    assert classify_event(is_recent_registration=True, is_recent_change=True) == "registration and change"


@responses.activate
def test_collect_labels_a_fresh_registration_as_registration_not_change(tmp_path):
    now = datetime.now(timezone.utc)
    responses.add(
        responses.GET, "https://rdap.org/domain/acmeinc.com",
        json={"events": [{"eventAction": "registration", "eventDate": (now - timedelta(days=10)).isoformat()}]},
        status=200,
    )
    source = DomainWhoisSource(_config(), cache=ResponseCache(tmp_path / "cache.db"), use_cache=False)
    with mock.patch("socket.getaddrinfo", side_effect=_fake_getaddrinfo):
        result = source.collect(Target(mode="company", query="Acme Inc"))

    matches = [f for f in result.findings if f.raw["domain"] == "acmeinc.com"]
    assert len(matches) == 1
    finding = matches[0]
    assert finding.raw["kind"] == "registration"
    assert "recent registration" in finding.title
    assert finding.quiet_reason == "Recent domain registration with no matching news found"


@responses.activate
def test_collect_labels_an_old_domain_with_a_recent_change_as_change_not_registration(tmp_path):
    now = datetime.now(timezone.utc)
    responses.add(
        responses.GET, "https://rdap.org/domain/acmeinc.com",
        json={"events": [
            {"eventAction": "registration", "eventDate": (now - timedelta(days=4000)).isoformat()},
            {"eventAction": "last changed", "eventDate": (now - timedelta(days=5)).isoformat()},
        ]}, status=200,
    )
    source = DomainWhoisSource(_config(), cache=ResponseCache(tmp_path / "cache.db"), use_cache=False)
    with mock.patch("socket.getaddrinfo", side_effect=_fake_getaddrinfo):
        result = source.collect(Target(mode="company", query="Acme Inc"))

    matches = [f for f in result.findings if f.raw["domain"] == "acmeinc.com"]
    assert len(matches) == 1
    finding = matches[0]
    assert finding.raw["kind"] == "change"
    assert "recent change" in finding.title
    assert finding.quiet_reason == "Recent domain change with no matching news found"
    assert "last changed" in finding.summary
