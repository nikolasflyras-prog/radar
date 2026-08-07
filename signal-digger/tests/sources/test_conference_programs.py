from datetime import timezone

from digger.sources.conference_programs import extract_pairs, program_date


def test_extract_pairs_finds_name_affiliation():
    text = "Keynote: Jane Chen (Acme Semiconductor) will discuss packaging trends"
    pairs = extract_pairs(text)
    assert pairs == [("Jane Chen", "Acme Semiconductor")]


def test_extract_pairs_no_match_returns_empty():
    assert extract_pairs("A general session with no speaker listed") == []


def test_program_date_prefers_explicit_date():
    date = program_date({"date": "2026-03-05", "year": 2026})
    assert date.isoformat() == "2026-03-05T00:00:00+00:00"


def test_program_date_falls_back_to_january_first_of_year():
    date = program_date({"year": 2025})
    assert date.year == 2025 and date.month == 1 and date.day == 1
    assert date.tzinfo == timezone.utc
