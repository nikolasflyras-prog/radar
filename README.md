# Spinout Radar

Spinout Radar is a public-signal early-warning system for semiconductor founder spinouts. It collects signals into SQLite, connects people and entities, applies explainable time-decayed scoring, and produces a weekly Markdown and self-contained HTML digest.

It does **not** access or automate LinkedIn. The report provides a ranked manual-review checklist, and observations can be added through the CLI.

## Version 0.4: signal classification

This release separates true formation evidence from ordinary semiconductor news:

- **Investigate now (60+)** — high-confidence, corroborated entity lead.
- **Watching (25–59)** — named entity with meaningful evidence but insufficient corroboration.
- **Emerging entity lead (8–24)** — named entity worth retaining and reviewing.
- **Spinout discovery inbox** — founder, stealth, formation, or personnel-change signals not yet tied confidently to an entity.
- **Industry intelligence** — relevant semiconductor technical or market news without company-formation evidence.

Financial vehicles such as fixed-income trusts, credit funds, partnerships, and investment products are rejected before scoring. Weak words such as `core`, `power`, and `logic` cannot qualify by themselves.

## Setup

Requires Python 3.11+.

```bash
python -m pip install -e ".[dev]"
radar init
radar run
```

Configure:

1. Set `contact_email` in `config/config.yaml`.
2. Maintain people in `config/watchlist_people.yaml`.
3. Optionally set `GITHUB_TOKEN` and `OPENCORPORATES_TOKEN` as environment variables or GitHub secrets.

## Main commands

```bash
radar init
radar run
radar run --source edgar
radar digest --regenerate
radar top --limit 20
radar stats
radar reset-data --yes
radar note person "Jane Chen" "LinkedIn now says Stealth — Founder"
radar backfill --source hn --months 6
radar undo-merge 12
```

`radar reset-data --yes` creates a timestamped backup before replacing the active database. It preserves configuration and watchlists.

## Digest sections

1. Investigate now
2. Watching
3. Emerging entity leads
4. Spinout discovery inbox
5. Industry intelligence
6. New relevant entities this week
7. Corroborated cluster watch
8. Signal-driven LinkedIn checks
9. Routine founder rotation
10. Possible entity merges
11. Source health

## Signal-quality changes

- Hacker News collection uses story results rather than comment matches.
- Keyword matching uses token and phrase boundaries, so `EDA` does not match *Cedar* and `ASIC` does not match *basic*.
- Form D filtering rejects funds, trusts, credit vehicles, hotels, healthcare, biotech, films, mining, and other obvious false positives.
- Legal entities such as LLCs and funds are not inserted into the people graph.
- One Form D containing many related persons does not automatically receive a cluster multiplier.
- Cluster Watch requires corroboration from multiple signals or sources.
- LinkedIn checks are split between actual recent signals and a clearly labeled five-person routine founder rotation.

## Source limitations

| Source | Current behavior |
|---|---|
| SEC EDGAR | Public daily indexes and filing XML; occasional SEC timeouts are reported as partial health. |
| USPTO | Live assignment search is unreliable; official bulk XML in `data/uspto-bulk/` is the recommended historical route. |
| GitHub | Public profiles/events; usefulness depends on GitHub handles in the watchlist. |
| Hacker News | Story-level discovery evidence, not identity proof. |
| RSS/news | Public feeds; exact semiconductor phrase matching. |
| Conferences | Requires current program URLs and selectors in `config/conferences.yaml`. |
| Incorporations | OpenCorporates requires a token; Delaware free bulk discovery is not fabricated. |
| Domains | Candidate-only DNS/RDAP/homepage corroboration. |

## Testing

```bash
python -m pytest -q
```

## Weekly GitHub Actions

The workflow runs Mondays at 11:00 UTC. Add repository secrets:

- `RADAR_CONTACT_EMAIL`
- `RADAR_GITHUB_TOKEN`
- `OPENCORPORATES_TOKEN` (optional)

Keep the repository private because watchlists and manual observations may be sensitive.
