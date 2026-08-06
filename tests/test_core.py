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

