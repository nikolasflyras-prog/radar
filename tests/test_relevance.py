from radar.relevance import (
    classify_public_signal,
    entity_is_excluded,
    entity_is_financial_vehicle,
    extract_candidate_entity,
    looks_like_affiliation,
    looks_like_company_candidate,
    looks_like_person,
    matched_terms,
    person_departure_matches,
)


def _cfg():
    return {
        "strong_terms": ["semiconductor", "silicon photonics", "ASIC", "RISC-V", "chiplet"],
        "contextual_terms": ["core", "logic", "power", "memory", "interconnect"],
        "startup_language": ["founded", "founder", "stealth", "seed round", "new startup"],
        "startup_weak_language": ["startup"],
    }


def test_exact_terms_avoid_substring_noise():
    assert matched_terms("Cedar Breaks", ["EDA"]) == []
    assert matched_terms("A basic tutorial", ["ASIC"]) == []
    assert matched_terms("New ASIC interconnect", ["ASIC", "interconnect"]) == ["ASIC", "interconnect"]


def test_organization_is_not_person():
    assert looks_like_person("Jane Q. Chen")
    assert not looks_like_person("Peachtree Credit Fund IV, LP")
    assert not looks_like_person("N/A General Partner LLC")


def test_financial_vehicle_is_excluded_even_on_core_match():
    assert entity_is_financial_vehicle("NHIT: Core Plus Fixed Income Trust")
    assert entity_is_excluded("NHIT: Core Plus Fixed Income Trust", "", ["investment fund"])
    assert not entity_is_financial_vehicle("CoreWeave")


def test_public_signal_classification_separates_spinout_from_industry():
    spinout = classify_public_signal("Acme founded a silicon photonics startup", _cfg())
    industry = classify_public_signal("New silicon photonics interconnect research", _cfg())
    generic_startup = classify_public_signal("Startup policy for the semiconductor ecosystem", _cfg())
    suppressed = classify_public_signal("Core Plus Fixed Income Trust", _cfg())
    assert spinout.category == "spinout"
    assert industry.category == "industry"
    assert generic_startup.category == "industry"
    assert suppressed.category == "suppressed"


def test_contextual_term_alone_does_not_qualify():
    assert classify_public_signal("A new power product", _cfg()).category == "suppressed"
    assert classify_public_signal("Power memory startup founded today", _cfg()).category == "spinout"


def test_candidate_entity_extraction_is_conservative():
    assert extract_candidate_entity("PhotonForge raises seed round for chiplet interconnect") == "PhotonForge"
    assert extract_candidate_entity("Can you reverse engineer an ASIC?") is None
    assert extract_candidate_entity("Startup Policy Launches The Semicon Consortium") is None
    assert not looks_like_company_candidate("Conference Archive")
    assert not looks_like_company_candidate("Semiconductor Market Forecast Report")


def test_affiliation_filter_rejects_navigation_labels():
    assert looks_like_affiliation("NVIDIA")
    assert looks_like_affiliation("Massachusetts Institute of Technology")
    assert not looks_like_affiliation("opens in new tab")
    assert not looks_like_affiliation("Conference Archive")
    assert not looks_like_affiliation("Exhibit Hall Floor Plan")


def test_watchlist_name_matching_avoids_substrings():
    from radar.relevance import matched_people, watchlist_identity_matches
    assert matched_people("Jane Chen founded PhotonForge", ["Jane Chen", "Chen Li"]) == ["Jane Chen"]
    people = [{"name": "Jane Chen", "known_aliases": ["Jane Q. Chen"]}]
    assert watchlist_identity_matches("Jane Q. Chen has left Marvell", people)[0]["name"] == "Jane Chen"


def _watched_pair():
    return [
        {"name": "Jane Chen", "known_aliases": [], "last_known_employer": "Marvell"},
        {"name": "Sam Lee", "known_aliases": [], "last_known_employer": "Intel"},
    ]


def test_person_departure_matches_requires_own_employer_and_departure_language():
    cfg = {"departure_language": ["has left", "departed"]}
    hits = person_departure_matches(
        "Jane Chen has left Marvell to work on something new", cfg, _watched_pair(),
    )
    assert [p["name"] for p in hits] == ["Jane Chen"]


def test_person_departure_matches_does_not_attribute_unrelated_employer():
    # "has left" is present and Intel is someone's employer, but Intel is not
    # Jane Chen's own employer -- this must not be attributed to her.
    cfg = {"departure_language": ["has left", "departed"]}
    hits = person_departure_matches(
        "Jane Chen commented after an engineer has left Intel", cfg, _watched_pair(),
    )
    assert hits == []


def test_person_departure_matches_requires_departure_language_not_just_employer_mention():
    cfg = {"departure_language": ["has left", "departed"]}
    hits = person_departure_matches(
        "Jane Chen still works at Marvell and gave a keynote", cfg, _watched_pair(),
    )
    assert hits == []


def test_formation_query_builder_is_bounded_and_high_intent():
    from radar.relevance import build_formation_queries
    cfg = {
        "formation_queries": ['"semiconductor startup" founder'],
        "news_query_domain_terms": ["chiplet", "silicon photonics"],
        "news_query_movement_terms": ["startup", "stealth"],
    }
    orgs = [{"name": "Marvell"}, {"name": "AMD"}]
    queries = build_formation_queries(cfg, orgs, max_orgs=1)
    assert queries[0] == '"semiconductor startup" founder'
    assert any('"chiplet"' in q and "stealth" in q for q in queries)
    assert any('"Marvell"' in q and "founder" in q for q in queries)
    assert not any('"AMD"' in q for q in queries)
