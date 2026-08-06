# Spinout Radar

Spinout Radar is a laptop-friendly, public-signal early-warning system for semiconductor founder spinouts. It collects independent signals into SQLite, resolves entity names, connects people seen together, applies explainable time-decayed scoring, and produces a Monday-ready Markdown and self-contained HTML digest.

It **does not access or automate LinkedIn**. Instead, the digest creates a ranked manual review checklist and the CLI accepts your observations as first-class signals.

## Ten-minute setup

Requires Python 3.11+.

```bash
cd spinout-radar
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

1. Change `contact_email` in `config/config.yaml`. The SEC expects a descriptive User-Agent with real contact information.
2. Replace the two placeholder people in `config/watchlist_people.yaml` with your watchlist. GitHub handles are the most useful optional field.
3. Create a GitHub personal access token with public-read access and expose it as `GITHUB_TOKEN`. The collector works unauthenticated at a much lower rate limit.
4. Optionally expose `OPENCORPORATES_TOKEN` for incorporation discovery.
5. Initialize and run:

```bash
radar init
radar run
open output/weekly-digest.html        # or open it from your file explorer
```

Every collector fails independently. A partial run still scores saved signals and writes a digest; the source-health section states what failed.

## Commands

```bash
radar init
radar run
radar run --source edgar
radar digest --regenerate
radar add-person "Jane Chen" --employer Marvell --github janechen
radar add-org "Example Silicon" --aliases "Example Silicon Inc."
radar note person "Jane Chen" "LinkedIn now says Stealth — Founder"
radar backfill --source hn --months 6
radar top --limit 20
radar undo-merge 12
```

Backfill is supported for `edgar`, `uspto`, and `hn`. SEC daily indexes do not exist on weekends or holidays; those expected misses are recorded in source health but do not stop the run.

## How scoring works

Weights and thresholds live in `config/config.yaml`. A patent reassignment from a watched company starts at 40; a domain that resolves and contains hiring language starts at 15; an incorporation keyword match starts at 5. Each signal decays with a 60-day half-life. Multiple independent source types increase confidence, three connected people in a 90-day window double the score, and people tagged `prior_founder` receive a 1.5× signal bonus.

- **Investigate now (60+)**: open every source, establish whether the entity and people are genuinely connected, then identify a warm introduction.
- **Watching (30–59)**: monitor; usually one corroborating source away from action.
- **Stored (<30)**: retained for later cross-reference but excluded from the main leaderboard.

Fuzzy entity matches at 90+ are safe only after suffix normalization; potential 75–89 matches are never silently merged and appear in the digest for review. Raw source strings remain on every signal.

## Source status (verified design, August 2026)

| Source | Implementation and honest limitation |
|---|---|
| SEC EDGAR | Uses the SEC's public daily master indexes and filing XML. This is the most dependable free discovery path; no key is required. |
| USPTO assignments | The Assignment Search interface has changed and its public JSON endpoint is unreliable. The URL is configurable and failures are explicit. When live queries fail, the collector parses official assignment bulk XML placed in `data/uspto-bulk/`; this is the recommended historical route. |
| GitHub | Uses official REST endpoints for public profiles, org membership, and public events. Org membership can be private; public event history is limited, so “activity drop” requires a baseline you set. |
| Hacker News | Uses the documented Algolia HN Search API. It is discovery evidence, not identity proof. |
| RSS/news | Uses public feeds and respects robots.txt when fetching. Feed lists are configurable. |
| Conferences | Uses public program pages and configurable CSS selectors. Empty shipped program lists are intentional because annual URLs change; add current/prior URLs before use. Parser errors fail soft. |
| Incorporations | OpenCorporates is supported when a token is supplied. Delaware is intentionally absent because it does not provide free bulk search. No registry coverage is fabricated. |
| Domains | Candidate-only DNS/RDAP and homepage corroboration. It never enumerates domains broadly. |

Official references: [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [SEC accessing EDGAR data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data), [GitHub REST API](https://docs.github.com/en/rest), [HN Algolia API](https://hn.algolia.com/api).

## Watchlist fields

People accept `name`, `known_aliases`, `github_usernames`, `personal_site`, `last_known_employer`, `specialty_tags`, `notes`, and optional `github_weekly_baseline`. Add `prior_founder` to `specialty_tags` to enable the founder bonus. Organizations accept `name` and `aliases`.

Conference entries use this shape:

```yaml
- name: ISSCC
  programs:
    - year: 2026
      url: https://public-program-url.example
      item_selector: ".paper"
```

## Safety and operations

- Public sources only; no paid data dependency.
- Descriptive User-Agent and configurable per-domain delays.
- `robots.txt` checked for general web pages. Official APIs are called directly under their published access policies.
- No login automation, anti-bot bypass, or headless-browser evasion.
- Keep the repository private because your watchlists and manual observations may be sensitive.
- SQLite writes are idempotent through source fingerprints. Back up `data/radar.db` before changing schema or running experimental importers.

## Testing

Tests use clearly marked local fixtures and never need the network:

```bash
pytest -q
```

## Weekly GitHub Actions

The included workflow runs Mondays at 11:00 UTC (7:00 a.m. Eastern during daylight time), commits the database and digest back to the private repository, and creates an issue if the job fails. Add repository secrets `RADAR_CONTACT_EMAIL` and `RADAR_GITHUB_TOKEN`; optionally add `OPENCORPORATES_TOKEN`.
