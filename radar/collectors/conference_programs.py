from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from .base import BaseCollector
from ..models import CollectorResult, Signal
from ..db import normalize_name


class ConferenceProgramsCollector(BaseCollector):
    name = "conferences"
    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        known_orgs = [o["name"] if isinstance(o, dict) else o for o in self.config.get("orgs", [])]
        for conf in self.config.get("conferences", []):
            for program in conf.get("programs", []):
                try:
                    html = self.get(program["url"]).text
                    soup = BeautifulSoup(html, "lxml")
                except Exception as exc: result.errors.append(f"{conf['name']} {program.get('year')}: {exc}"); continue
                blocks = soup.select(program.get("item_selector", "article, .session, .paper, li"))
                result.rows_fetched += len(blocks)
                for block in blocks:
                    text = " ".join(block.stripped_strings)
                    if len(text) < 20: continue
                    observations = set()
                    # Common program styles: "Jane Q. Chen (Lattice Labs)" and
                    # names followed within the same short block by a known org.
                    for person, affiliation in re.findall(r"([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){1,3})\s*\(([^()]{2,80})\)", text):
                        observations.add((person.strip(), affiliation.strip()))
                    for old in known_orgs:
                        pattern = re.compile(rf"([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+)+).{{0,80}}\b({re.escape(old)})\b")
                        observations.update((p.strip(), a.strip()) for p, a in pattern.findall(text))
                    for person, affiliation in observations:
                        signal_type = "conference_affiliation_observation"
                        prior = []
                        if self.db:
                            prior = self.db.rows("""SELECT e.canonical_name FROM signals s JOIN entities e ON e.id=s.entity_id
                                JOIN signal_people sp ON sp.signal_id=s.id JOIN people p ON p.id=sp.person_id
                                WHERE s.source='conferences' AND p.normalized_name=? ORDER BY s.observed_at DESC""",
                                (normalize_name(person),))
                        old_affiliations = {x["canonical_name"] for x in prior}
                        departed = [x for x in old_affiliations if x in known_orgs and x.casefold() != affiliation.casefold()]
                        if departed: signal_type = "conference_affiliation_change"
                        result.signals.append(Signal(source=self.name, signal_type=signal_type,
                            person_names=[person], entity_name=affiliation, observed_at=datetime(int(program["year"]),1,1,tzinfo=timezone.utc),
                            title=f"{person} at {conf['name']} {program['year']}", url=program["url"],
                            summary=f"Observed affiliation: {affiliation}" + (f"; prior watched affiliation: {', '.join(departed)}" if departed else ""),
                            raw={"text": text[:1000]}, source_key=f"conf:{conf['name']}:{program['year']}:{person}:{affiliation}"))
        return result
