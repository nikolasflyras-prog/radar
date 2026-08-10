from digger.textutil import classify_ma_or_general, contains_term, mentions_target, normalize


def test_normalize_strips_company_suffixes():
    assert normalize("Acme, Inc.") == normalize("Acme LLC")


def test_contains_term_is_word_bounded():
    assert contains_term("Acme acquires Widgets Co", "acquires")
    assert not contains_term("Acmeacquires", "acquires")


def test_mentions_target_matches_normalized_form():
    assert mentions_target("A press note about Acme, Inc. today", "Acme")


def test_classify_ma_or_general_detects_deal_language():
    category, hits = classify_ma_or_general("Acme to acquire Widgets Co in definitive agreement")
    assert category == "ma_deal"
    assert "acquire" in hits


def test_classify_ma_or_general_defaults_to_general():
    category, hits = classify_ma_or_general("Acme launches a new product line")
    assert category == "general_signal"
    assert hits == []
