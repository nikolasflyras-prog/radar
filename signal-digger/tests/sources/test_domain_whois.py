from digger.sources.domain_whois import domain_candidates, rdap_event_date


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
