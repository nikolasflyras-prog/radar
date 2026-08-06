from radar.relevance import (
    classify_public_signal,
    entity_is_excluded,
    entity_is_financial_vehicle,
    extract_candidate_entity,
    looks_like_person,
    matched_terms,
)


def _cfg():
    return {
        "strong_terms": ["semiconductor", "silicon photonics", "ASIC", "RISC-V", "chiplet"],
        "contextual_terms": ["core", "logic", "power", "memory", "interconnect"],
        "startup_language": ["startup", "founded", "founder", "launched", "stealth", "seed round"],
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
    spinout = classify_public_signal("Acme launched a silicon photonics startup", _cfg())
    industry = classify_public_signal("New silicon photonics interconnect research", _cfg())
    suppressed = classify_public_signal("Core Plus Fixed Income Trust", _cfg())
    assert spinout.category == "spinout"
    assert industry.category == "industry"
    assert suppressed.category == "suppressed"


def test_contextual_term_alone_does_not_qualify():
    assert classify_public_signal("A new power product", _cfg()).category == "suppressed"
    assert classify_public_signal("Power memory startup founded today", _cfg()).category == "spinout"


def test_candidate_entity_extraction_is_conservative():
    assert extract_candidate_entity("PhotonForge raises seed round for chiplet interconnect") == "PhotonForge"
    assert extract_candidate_entity("Can you reverse engineer an ASIC?") is None
