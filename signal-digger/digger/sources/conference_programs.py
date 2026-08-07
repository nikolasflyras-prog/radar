from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..models import SourceResult, Target
from ..textutil import mentions_target, normalize
from .base import BaseSource

SPEAKER_AFFILIATION_RE = re.compile(r"([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){1,3})\s*\(([^()]{2,100})\)")


def extract_pairs(text: str) -> list[tuple[str, str]]:
    """Pull "Name (Affiliation)" pairs out of a program block. Pure function so the
    regex can be tested against fixture text without fetching a real page."""
    return SPEAKER_AFFILIATION_RE.findall(text)


def program_date(program: dict) -> datetime:
    value = program.get("date")
    if value:
        try:
            return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime(int(program.get("year", datetime.now().year)), 1, 1, tzinfo=timezone.utc)


class ConferenceProgramsSource(BaseSource):
    """Conference program / speaker-list pages configured under `conferences`,
    scanned for the target's name and, when found, a nearby "Name (Affiliation)"
    pair — the closest thing to an affiliation change public program pages give."""

    name = "conference_programs"

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        conferences = self.config.get("conferences", [])
        if not conferences:
            result.skipped_reason = "no conferences configured"
            return result
        known_people = {normalize(p.get("name", "")): p for p in self.config.get("known_people", [])}
        for conf in conferences:
            for program in conf.get("programs", []):
                try:
                    html = self.fetch_text(program["url"], respect_robots=program.get("respect_robots", True))
                    soup = BeautifulSoup(html, "lxml")
                except Exception as exc:
                    result.errors.append(f"{conf.get('name')} {program.get('year')}: {exc}")
                    continue
                selector = program.get("item_selector", "tr, article, .session, .paper, li")
                blocks = soup.select(selector) or [soup.body or soup]
                result.rows_fetched += len(blocks)
                observed = program_date(program)
                for block in blocks:
                    text = " ".join(block.stripped_strings)
                    if len(text) < 12 or not mentions_target(text, target.query):
                        continue
                    pairs = extract_pairs(text)
                    if not pairs:
                        result.findings.append(self.finding(
                            source=self.name, category="general_signal",
                            title=f"{target.query} mentioned at {conf.get('name')} {program.get('year')}",
                            observed_at=observed, url=program["url"],
                            summary=text[:220],
                            entities=[target.query],
                            raw={"conference": conf.get("name"), "year": program.get("year")},
                            dedupe_key=f"conf:{conf.get('name')}:{program.get('year')}:{normalize(text)[:80]}",
                        ))
                        continue
                    for person_name, affiliation in pairs:
                        known = known_people.get(normalize(person_name))
                        prior_employer = known.get("employer") if known else None
                        changed = bool(prior_employer and normalize(affiliation) != normalize(prior_employer))
                        result.findings.append(self.finding(
                            source=self.name, category="general_signal",
                            title=f"{person_name} at {conf.get('name')} {program.get('year')}",
                            observed_at=observed, url=program["url"],
                            summary=f"Listed affiliation: {affiliation}" + (f"; prior known employer: {prior_employer}" if prior_employer else ""),
                            people=[person_name], entities=[affiliation],
                            raw={"conference": conf.get("name"), "year": program.get("year"), "affiliation_changed": changed},
                            quiet=changed,
                            quiet_reason="Affiliation differs from previously known employer" if changed else "",
                            dedupe_key=f"conf:{conf.get('name')}:{program.get('year')}:{normalize(person_name)}:{normalize(affiliation)}",
                        ))
        return result
