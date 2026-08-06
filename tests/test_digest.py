from datetime import datetime, timezone
from pathlib import Path

from radar.db import Database
from radar.digest import generate
from radar.models import Signal


def _template(tmp_path: Path):
    (tmp_path / "templates").mkdir()
    source = Path(__file__).parents[1] / "templates" / "digest.html.j2"
    (tmp_path / "templates" / "digest.html.j2").write_text(source.read_text())


def _cfg():
    return {
        "keywords": {
            "strong_terms": ["silicon photonics", "ASIC", "semiconductor"],
            "contextual_terms": ["interconnect", "core"],
            "startup_language": ["startup", "launch hn", "founded"],
        },
        "people": [{"name": "Jane Chen", "specialty_tags": ["prior_founder"], "last_known_employer": "Marvell"}],
        "display": {"routine_review_limit": 5, "signal_review_limit": 10},
    }


def test_empty_digest_is_generated(tmp_path: Path):
    _template(tmp_path)
    db = Database(tmp_path / "data/radar.db")
    db.initialize()
    md, html = generate(db, tmp_path, _cfg())
    text = md.read_text()
    assert "Spinout discovery inbox" in text
    assert "Industry intelligence" in text
    assert "Routine founder rotation" in text
    assert "Jane Chen" in text
    assert "Spinout Radar" in html.read_text()


def test_spinout_and_industry_are_separated(tmp_path: Path):
    _template(tmp_path)
    db = Database(tmp_path / "data/radar.db")
    db.initialize()
    now = datetime.now(timezone.utc)
    db.insert_signal(Signal(
        source="hn", signal_type="spinout_discovery", title="Launch HN: New silicon photonics startup",
        observed_at=now, url="https://example.com/spinout",
        summary="HN spinout; domain terms: silicon photonics", raw={
            "classification": "spinout", "matched_strong_terms": ["silicon photonics"],
            "startup_language": ["startup", "launch hn"], "points": 20,
        }, source_key="fixture:spinout",
    ))
    db.insert_signal(Signal(
        source="rss", signal_type="industry_intelligence", title="New silicon photonics interconnect research",
        observed_at=now, url="https://example.com/industry",
        summary="Industry research", raw={
            "classification": "industry", "matched_strong_terms": ["silicon photonics"],
            "matched_contextual_terms": ["interconnect"],
        }, source_key="fixture:industry",
    ))
    md, _ = generate(db, tmp_path, _cfg())
    text = md.read_text()
    assert "New silicon photonics startup" in text
    assert "New silicon photonics interconnect research" in text
    assert text.index("New silicon photonics startup") < text.index("New silicon photonics interconnect research")


def test_watchlist_mentions_and_github_candidates_are_rendered(tmp_path: Path):
    _template(tmp_path)
    db = Database(tmp_path / "data/radar.db")
    db.initialize()
    db.seed_people([{"name": "Jane Chen", "last_known_employer": "Marvell", "specialty_tags": ["prior_founder"]}])
    now = datetime.now(timezone.utc)
    db.insert_signal(Signal(
        source="gdelt", signal_type="watchlist_public_mention", title="Jane Chen speaks about chiplets",
        observed_at=now, person_names=["Jane Chen"], url="https://example.com/jane",
        summary="Public watchlist mention", raw={"classification": "watchlist"}, source_key="fixture:mention",
    ))
    db.insert_signal(Signal(
        source="github", signal_type="github_identity_candidate", title="Possible GitHub identity",
        observed_at=now, person_names=["Jane Chen"], url="https://github.com/janechen",
        summary="Confidence 8/10", raw={
            "candidate_username": "janechen", "confidence": 8,
            "reasons": ["exact profile-name match", "company matches last known employer"],
            "company": "Marvell",
        }, source_key="fixture:github-candidate",
    ))
    md, html = generate(db, tmp_path, _cfg())
    text = md.read_text()
    assert "Watchlist people mentioned publicly" in text
    assert "Jane Chen speaks about chiplets" in text
    assert "GitHub identity candidates" in text
    assert "@janechen" in text
    assert "@janechen" in html.read_text()
