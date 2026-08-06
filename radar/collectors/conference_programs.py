from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from .base import BaseCollector
from ..db import normalize_name
from ..models import CollectorResult, Signal
from ..relevance import contains_term, looks_like_person


class ConferenceProgramsCollector(BaseCollector):
    name = "conferences"

    @staticmethod
    def _date(program: dict) -> datetime:
        value = program.get("date")
        if value:
            try:
                return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime(int(program["year"]), 1, 1, tzinfo=timezone.utc)

    @staticmethod
    def _nearby(text: str, needle: str, radius: int = 180) -> str:
        match = re.search(re.escape(needle), text, re.IGNORECASE)
        if not match:
            return text[: radius * 2]
        return text[max(0, match.start() - radius): match.end() + radius]

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        org_rows = self.config.get("orgs", [])
        known_orgs: list[str] = []
        for org in org_rows:
            if isinstance(org, dict):
                known_orgs.extend([org.get("name", ""), *org.get("aliases", [])])
            else:
                known_orgs.append(str(org))
        known_orgs = [x for x in dict.fromkeys(known_orgs) if x]
        people_cfg = self.config.get("people", [])

        for conf in self.config.get("conferences", []):
            for program in conf.get("programs", []):
                try:
                    html = self.get(program["url"], respect_robots=program.get("respect_robots", True)).text
                    soup = BeautifulSoup(html, "lxml")
                except Exception as exc:
                    result.errors.append(f"{conf['name']} {program.get('year')}: {exc}")
                    continue
                selector = program.get("item_selector", "tr, article, .session, .paper, li")
                blocks = soup.select(selector)
                if not blocks:
                    blocks = [soup.body or soup]
                result.rows_fetched += len(blocks)
                observed = self._date(program)
                emitted: set[tuple[str, str]] = set()

                for block in blocks:
                    text = " ".join(block.stripped_strings)
                    if len(text) < 12:
                        continue
                    observations: set[tuple[str, str]] = set()
                    for person, affiliation in re.findall(
                        r"([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){1,3})\s*\(([^()]{2,80})\)", text,
                    ):
                        if looks_like_person(person):
                            observations.add((person.strip(), affiliation.strip()))

                    for person in people_cfg:
                        names = [person.get("name", ""), *person.get("known_aliases", [])]
                        matched_name = next((n for n in names if n and contains_term(text, n)), None)
                        if not matched_name:
                            continue
                        context = self._nearby(text, matched_name)
                        affiliations = [org for org in known_orgs if contains_term(context, org)]
                        affiliation = affiliations[0] if len(affiliations) == 1 else ""
                        observations.add((person["name"], affiliation))

                    for person_name, affiliation in observations:
                        key = (normalize_name(person_name), normalize_name(affiliation))
                        if key in emitted:
                            continue
                        emitted.add(key)
                        watch_row = next(
                            (p for p in people_cfg if normalize_name(p.get("name", "")) == normalize_name(person_name)), None,
                        )
                        last_employer = (watch_row or {}).get("last_known_employer") or ""
                        changed = bool(
                            affiliation and last_employer and normalize_name(affiliation) != normalize_name(last_employer)
                        )
                        signal_type = "conference_affiliation_change" if changed else "conference_watchlist_mention"
                        result.signals.append(Signal(
                            source=self.name,
                            signal_type=signal_type,
                            person_names=[person_name],
                            entity_name=affiliation or None,
                            observed_at=observed,
                            title=f"{person_name} at {conf['name']} {program['year']}",
                            url=program["url"],
                            summary=(
                                f"Conference program mention; affiliation: {affiliation or 'not confidently parsed'}; "
                                f"last known employer: {last_employer or 'unknown'}"
                            ),
                            raw={
                                "conference": conf["name"], "year": program["year"], "text": text[:1200],
                                "affiliation_changed": changed,
                            },
                            base_weight=25 if changed else 4,
                            source_key=f"conf:{conf['name']}:{program['year']}:{normalize_name(person_name)}:{normalize_name(affiliation)}",
                        ))
        return result
