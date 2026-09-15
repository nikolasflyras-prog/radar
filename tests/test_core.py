from datetime import datetime, timezone
from pathlib import Path
from radar.db import Database, normalize_name
from radar.models import Signal
from radar.score import score_all


def test_normalize_company_suffixes():
    assert normalize_name("Lattice-IO, Inc.") == normalize_name("lattice io LLC")


def test_signal_deduplication_and_scoring(tmp_path: Path):
    db = Database(tmp_path / "radar.db"); db.initialize()
    signal = Signal(source="edgar", signal_type="form_d_keyword_issuer", title="Form D: Lattice IO",
                    observed_at=datetime.now(timezone.utc), entity_name="Lattice IO, Inc.",
                    person_names=["Jane Chen", "Sam Lee", "Ari Patel"], source_key="fixture:formd:1")
    assert db.insert_signal(signal) is True
    assert db.insert_signal(signal) is False
    db.insert_signal(Signal(source="uspto", signal_type="patent_bigco_to_new", title="Marvell to Lattice IO",
        observed_at=datetime.now(timezone.utc), entity_name="Lattice IO", person_names=["Jane Chen", "Sam Lee", "Ari Patel"], source_key="fixture:patent:1"))
    score_all(db, {"scoring":{"half_life_days":60,"cluster_window_days":90,"investigate_threshold":60,"watching_threshold":30}})
    row = db.rows("SELECT * FROM scores")[0]
    assert row["score"] >= 60
    assert row["tier"] == "Investigate now"


def test_departure_signal_carries_formation_intent_to_watching(tmp_path: Path):
    db = Database(tmp_path / "radar.db"); db.initialize()
    now = datetime.now(timezone.utc)
    db.insert_signal(Signal(source="rss", signal_type="news_departure_stealth",
        title="Jane Chen has left Marvell to build a stealth startup",
        observed_at=now, entity_name="Stealth Photon Co", person_names=["Jane Chen"],
        base_weight=20, source_key="rss:departure:1"))
    db.insert_signal(Signal(source="hn", signal_type="hn_keyword",
        title="HN discussion mentions Stealth Photon Co",
        observed_at=now, entity_name="Stealth Photon Co", base_weight=3, source_key="hn:1"))
    score_all(db, {"scoring":{"half_life_days":60,"investigate_threshold":60,"watching_threshold":25,"discovery_threshold":8}})
    row = db.rows("SELECT * FROM scores")[0]
    assert row["tier"] in {"Watching", "Investigate now"}


def test_corroboration_without_formation_intent_cannot_reach_watching(tmp_path: Path):
    db = Database(tmp_path / "radar.db"); db.initialize()
    now = datetime.now(timezone.utc)
    db.insert_signal(Signal(source="domains", signal_type="domain_hiring", title="Domain careers page",
        observed_at=now, entity_name="Established Matrix", base_weight=15, source_key="domain:1"))
    db.insert_signal(Signal(source="domains", signal_type="domain_hiring", title="Second domain careers page",
        observed_at=now, entity_name="Established Matrix", base_weight=15, source_key="domain:2"))
    db.insert_signal(Signal(source="conferences", signal_type="conference_watchlist_mention", title="Conference mention",
        observed_at=now, entity_name="Established Matrix", person_names=["Jane Chen"], base_weight=4, source_key="conf:1"))
    score_all(db, {"scoring":{"half_life_days":60,"investigate_threshold":60,"watching_threshold":25,"discovery_threshold":8}})
    row = db.rows("SELECT * FROM scores")[0]
    assert row["score"] >= 25
    assert row["tier"] == "Discovery"
