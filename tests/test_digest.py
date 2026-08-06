from pathlib import Path
from radar.db import Database
from radar.digest import generate


def test_empty_digest_is_generated(tmp_path: Path):
    (tmp_path / "templates").mkdir()
    source = Path(__file__).parents[1] / "templates" / "digest.html.j2"
    (tmp_path / "templates" / "digest.html.j2").write_text(source.read_text())
    db = Database(tmp_path / "data/radar.db"); db.initialize()
    md, html = generate(db, tmp_path)
    assert "Manual LinkedIn review sheet" in md.read_text()
    assert "Spinout Radar" in html.read_text()

