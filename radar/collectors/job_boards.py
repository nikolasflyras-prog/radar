from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .base import BaseCollector
from ..models import CollectorResult, Signal
from ..relevance import matched_terms


class JobBoardsCollector(BaseCollector):
    """Candidate-only corroboration against public Greenhouse/Lever job boards.

    A "Founding Engineer" listing is often public before any press coverage
    exists, making this one of the earliest available public signals of
    company formation. Neither ATS offers a company-agnostic public search,
    so this cannot discover new entities from scratch -- it checks candidate
    entity names other collectors have already surfaced (same pattern as
    domains_whois.py). ATS slugs are shared across millions of unrelated
    companies, so a board simply existing under a name-derived slug is not
    itself evidence: only a posting whose title names a founding-stage role
    AND whose content matches a semiconductor-domain term counts.
    """

    name = "jobboards"

    @staticmethod
    def _slugs(name: str) -> list[str]:
        words = re.findall(r"[a-z0-9]+", (name or "").casefold())
        if not words:
            return []
        return list(dict.fromkeys(["".join(words), "-".join(words)]))

    def _greenhouse(self, slug: str) -> list[dict]:
        payload = self.get(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", respect_robots=False,
        ).json()
        return payload.get("jobs", []) if isinstance(payload, dict) else []

    def _lever(self, slug: str) -> list[dict]:
        payload = self.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", respect_robots=False).json()
        return payload if isinstance(payload, list) else []

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        if not self.db:
            result.errors.append("Job-board corroboration requires the candidate database")
            return result

        keyword_cfg = self.config.get("keywords", {})
        strong_terms = keyword_cfg.get("strong_terms", keyword_cfg.get("terms", []))
        founding_titles = keyword_cfg.get("founding_hire_titles", [])
        candidates = self.db.rows(
            "SELECT canonical_name FROM entities WHERE first_seen >= ? ORDER BY first_seen DESC LIMIT 100",
            ((since or self.utcnow() - timedelta(days=30)).isoformat(),),
        )

        for row in candidates:
            slugs = self._slugs(row["canonical_name"])
            if not slugs:
                continue
            best_signal: Signal | None = None

            for slug in slugs[:2]:
                for board, fetch in (("greenhouse", self._greenhouse), ("lever", self._lever)):
                    try:
                        postings = fetch(slug)
                    except Exception:
                        continue
                    result.rows_fetched += len(postings)
                    for posting in postings:
                        title = str(posting.get("title") or "")
                        content = str(posting.get("content") or posting.get("descriptionPlain") or "")
                        founding_hits = matched_terms(title, founding_titles)
                        domain_hits = matched_terms(f"{title} {content}", strong_terms)
                        if not (founding_hits and domain_hits):
                            continue
                        url = posting.get("absolute_url") or posting.get("hostedUrl") or f"https://{board}.io/{slug}"
                        signal = Signal(
                            source=self.name,
                            signal_type="hiring_board_founding",
                            entity_name=row["canonical_name"],
                            observed_at=self.utcnow(),
                            title=f"{board.title()} posting: {title}",
                            url=url,
                            summary=f"Founding-stage hiring on public {board} board ({slug}); domain terms: {', '.join(domain_hits)}",
                            raw={
                                "board": board, "slug": slug, "job_title": title,
                                "founding_terms": founding_hits, "domain_terms": domain_hits,
                            },
                            base_weight=18,
                            source_key=f"{board}:{slug}:{posting.get('id') or url}",
                        )
                        if best_signal is None:
                            best_signal = signal

            # At most one job-board signal per entity per run -- corroboration, not stacked evidence.
            if best_signal is not None:
                result.signals.append(best_signal)

        return result
