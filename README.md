# Spinout Radar

Spinout Radar is a public-signal early-warning system for semiconductor founder spinouts. It collects independent signals into SQLite, resolves people and entities, applies explainable time-decayed scoring, and produces a weekly Markdown and self-contained HTML digest.

It does **not** access or automate LinkedIn. The digest provides targeted manual-review checklists, and your observations can be added through the CLI.

## Version 0.5: source expansion and watchlist intelligence

Version 0.5 keeps the conservative v0.4 classification rules and expands the number of high-value inputs:

- Adds high-intent public-news discovery through the GDELT DOC API.
- Searches combinations of semiconductor terms with founder, stealth, spinout, fundraising, and departure language.
- Rotates targeted searches across prior founders and watched employers.
- Adds a dedicated **Watchlist people mentioned publicly** section.
- Adds conservative GitHub-handle discovery for watchlist people without confirmed usernames.
- Adds `radar confirm-github` to persist a manually verified handle.
- Adds current official program pages for ISSCC, Hot Chips, DAC, and IEDM.
- Separates unresolved spinout evidence from ordinary industry intelligence.
- Runs the test suite before the scheduled Monday collection.

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
3. Keep the repository private because the watchlist and manual observations may be sensitive.
4. Optionally set `GITHUB_TOKEN` and `OPENCORPORATES_TOKEN` as environment variables or GitHub Actions secrets.

## Main commands

```bash
radar init
radar run
radar run --source gdelt
radar run --source googlenews
radar run --source github
radar digest --regenerate
radar top --limit 20
radar stats
radar github-candidates --limit 20
radar confirm-github "Jane Chen" janechen
radar reset-data --yes
radar note person "Jane Chen" "LinkedIn now says Stealth — Founder"
radar backfill --source gdelt --months 2
radar undo-merge 12
```

`radar reset-data --yes` creates a timestamped backup before replacing the active database. It preserves configuration and watchlists.

## Digest sections

1. Investigate now
2. Watching
3. Emerging entity leads
4. Spinout discovery inbox
5. Industry intelligence
6. Watchlist people mentioned publicly
7. GitHub identity candidates
8. New relevant entities this week
9. Corroborated cluster watch
10. Signal-driven LinkedIn checks
11. Routine founder rotation
12. Possible entity merges
13. Source health

## How public-news discovery works

The GDELT and RSS collectors do not treat every semiconductor article as a startup lead. A story generally needs:

- a strong semiconductor term, or multiple contextual semiconductor terms; and
- founder, startup, stealth, spinout, fundraising, formation, or departure language.

Named watchlist people are retained in a separate watchlist-mention section even when the story is not strong enough to count as a spinout. Ordinary technical and market stories remain in Industry Intelligence.

## GitHub identity workflow

For people with confirmed handles, the collector monitors public profile fields, organizations, events, and configured activity baselines.

For a small rotating set of people without handles, it searches GitHub's public user index and only proposes a profile when the name matches exactly and there is additional corroboration such as an employer match or semiconductor terms in the profile.

Review candidates with:

```bash
radar github-candidates
```

After manually confirming a match:

```bash
radar confirm-github "Jane Chen" janechen
```

The command updates `config/watchlist_people.yaml`; it never auto-confirms an identity.

## Conference tracking

`config/conferences.yaml` includes current official public pages for:

- ISSCC 2026 program overview
- Hot Chips 2026 advance program
- DAC 2026 program
- IEDM 2026 program

The collector prioritizes exact watchlist-name matches and only infers affiliations from nearby text. A different affiliation from the last known employer is treated as a stronger signal than a simple program mention.

## Source limitations

| Source | Current behavior |
|---|---|
| GDELT | High-intent public-news search over a recent rolling window; discovery evidence, not proof. |
| SEC EDGAR | Public daily indexes and filing XML; occasional SEC errors are reported as partial health. |
| USPTO | Live assignment search is unreliable; official bulk XML in `data/uspto-bulk/` is the recommended historical route. |
| GitHub | Public profiles and activity; identity candidates require manual confirmation. |
| Hacker News | Story-level discovery evidence, not identity proof. |
| RSS/news | Public feeds classified into spinout, watchlist mention, industry, or suppressed. |
| Conferences | Exact-name watchlist matching on configured official public program pages. |
| Incorporations | OpenCorporates requires a token; Delaware free bulk discovery is not fabricated. |
| Domains | Candidate-only DNS/RDAP/homepage corroboration. |

## Testing

```bash
python -m pytest -q
```

## Weekly GitHub Actions

The workflow runs Mondays at 11:00 UTC and tests the project before collecting. Add repository secrets:

- `RADAR_CONTACT_EMAIL`
- `RADAR_GITHUB_TOKEN`
- `OPENCORPORATES_TOKEN` (optional)
