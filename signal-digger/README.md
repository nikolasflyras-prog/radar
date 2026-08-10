# Signal Digger

Public-signal research CLI for semiconductors and compute infrastructure.
Run a one-off company, sector, or person investigation, or execute a daily
multi-query watchlist that deduplicates, scores, remembers, and publishes new
findings to ATTENUA. One-off runs still produce matching Markdown and
self-contained HTML reports.

## Setup

```bash
cd signal-digger
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config/config.example.yaml config/config.yaml   # optional but recommended
```

Edit `config/config.yaml` — at minimum set `contact_email` (several sources'
etiquette expects a real contact point in the User-Agent). Everything else has
a working default; see the comments in `config/config.example.yaml`.

Keep authenticated source keys and the publishing credential in environment
variables rather than committing them:

```bash
export USPTO_API_KEY="..."        # free USPTO Open Data Portal key
export OPENALEX_API_KEY="..."     # OpenAlex API key
export ATTENUA_INGEST_TOKEN="..." # optional fallback for a manual publish
```

## Usage

```bash
digger run "Company Name"
digger run --sector "semiconductor packaging"
digger run --person "Jane Chen"

digger run "Company Name" --since-days 30       # narrower lookback window
digger run "Company Name" --no-cache             # bypass the response cache
digger run "Company Name" --sources sec_edgar,news_gdelt,job_boards
digger run "Company Name" --output ./my-reports
digger list-sources                              # see every source and its supported modes
```

For the daily multi-query feed:

```bash
cp config/searches.example.yaml config/searches.yaml
digger daily --queries config/searches.yaml
```

The aggregator removes tracking parameters, merges duplicate URLs across
queries and sources, applies an explainable priority score, suppresses
previously published findings, writes `output/daily/latest.json`, and POSTs
the edition when `daily.publish_url` is set. Use `--include-seen` for a full
refresh.

Exactly one of the `COMPANY` argument, `--sector`, or `--person` must be
given. Each run writes a `.md` and a `.html` report sharing the same name —
`output/<mode>-<slug>-<timestamp>.{md,html}` (or wherever `--output` /
`config.report.output_dir` points) — built from the same underlying data, so
they never disagree on what's quiet or how things are sorted.

## How a run works

Every applicable source runs concurrently in a thread pool. Each source:

1. Checks the SQLite response cache (`data/cache.db`) for a fresh-enough raw
   response before touching the network.
2. Respects `robots.txt` and its own configured per-domain rate limit.
3. Never raises past its own boundary — `BaseSource.run()` catches everything
   and turns a failure into an error entry on that source's result. A report
   with 7 out of 10 sources succeeding is still a useful report; the "Source
   Run Health" section at the bottom of every report says exactly which
   sources came back short and why.

The report is organized by **category**, not by source, sorted newest-first
within each section:

- **Quiet signals worth a second look** (top) — findings a source flagged
  quiet directly (a "Founding Engineer" posting, a domain re-registration, a
  hiring surge, a GitHub bio change) plus a correlation pass: any patent
  transfer, hiring surge, or domain event with no news finding within
  `quiet_signals.correlation_window_days` (default 21) of it gets flagged
  here too. This section is the point of the tool — the loud stuff you'd find
  anyway lives below it.
- **M&A & Deal Activity**
- **People & Staff Movement**
- **General & Other Signals**
- **Source Run Health** — always present, always honest about partial runs.

## Sources

Registered in `digger/sources/__init__.py` as a plain `name -> class` dict
(`SOURCES`). Adding a source later is one new module implementing
`BaseSource` plus one line in that dict — no other refactor.

| Source | Modes | What it returns |
|---|---|---|
| `sec_edgar` | company, sector | SEC EDGAR full-text search for `8-K` (Item 1.01/2.01), `S-4`, and `DEFM14A` filings naming the target — the actual deal paperwork. |
| `ftc_hsr` | company, sector | FTC Hart-Scott-Rodino early-termination notices: public confirmation a reportable acquisition cleared antitrust review. Scrapes the FTC's listing page (URL configurable under `ftc_hsr.listing_url`). |
| `uspto_assignments` | company, sector | USPTO patent assignment records — bulk transfers of patents to or from the target. Rarely covered in the press on its own; a prime candidate for the quiet-signals section. |
| `sec_form_d` | company, sector | SEC Form D and D/A filings that reveal private financings and amendments. |
| `arxiv` | all | Recent arXiv research papers matched through the public Atom API. |
| `openalex` | all | Scholarly works and citation metadata from OpenAlex. Requires `OPENALEX_API_KEY`. |
| `usaspending` | company, sector | Federal grants and contracts from the official USAspending award-search API. |
| `news_gdelt` | all | GDELT DOC 2.0 news search. Runs one deal-language query and one broad recency query, then buckets every article into `ma_deal` or `general_signal` by whether it actually contains M&A vocabulary. |
| `news_rss` | all | RSS search: any feeds under `rss_feeds`, plus an automatic Google News RSS query for the target (works with zero configuration). Same M&A/general bucketing as `news_gdelt`. |
| `github_people` | company, person | Public GitHub activity for people listed in `known_people`: profile bio/company-field changes and public org membership. Without a `known_people` entry matching the target, this source skips cleanly (not an error). |
| `hackernews` | all | Hacker News via the Algolia search API: story mentions, "Who's hiring?" thread comments naming the target (flagged quiet — self-identification with no announcement), and other comment mentions. |
| `job_boards` | company, sector | Greenhouse and Lever public job-board APIs. Flags `"Founding [Role]"` postings directly (an early signal on its own) and hiring surges versus the previous cached posting count. Company runs use `job_boards.slug_overrides` or a best-effort company-name guess; sector runs use only explicitly configured `greenhouse_slugs` / `lever_slugs`, avoiding meaningless sector-name guesses. |
| `domain_whois` | company | RDAP (WHOIS successor) lookups on domains guessed from a company name (`.com`, `.ai`, `.io`, `.co`). Flags registrations and registrant/registrar changes within separately configurable 90-day windows. Sector and person searches skip this source because guessed domains for those modes produce unrelated false positives. |
| `conference_programs` | all | Scans configured conference program/speaker-list pages (`conferences`) for the target's name and, when found, a nearby `"Name (Affiliation)"` pair. Flags an affiliation that differs from a `known_people` entry's recorded employer. |

`job_boards`, `sec_edgar`, `sec_form_d`, `ftc_hsr`, `usaspending`, and
`uspto_assignments` only run for
company/sector targets — they're inherently per-employer, not per-person.
`domain_whois` only runs for company targets. `github_people` only runs for
company/person targets, since it needs a named roster to check.

## Caching

Raw responses (not parsed findings) are cached in SQLite at `data/cache.db`,
keyed by `(source, url, params)` with a per-source TTL from
`cache.ttl_hours` in the config. `--no-cache` bypasses it entirely for one
run without deleting anything. One-off runs do not accumulate findings. Daily
runs additionally keep only finding fingerprints and first/last-seen
timestamps in `data/daily.db`, so the public page receives new signals instead
of repeating yesterday's edition.

## Daily scheduling

Copy `deploy/daily-intelligence.yml` to the repository root at
`.github/workflows/daily-intelligence.yml`. Add repository secrets
`DIGGER_CONTACT_EMAIL`, `USPTO_API_KEY`, and `OPENALEX_API_KEY`. The workflow
uses GitHub OIDC to obtain a short-lived, repository-bound publishing identity,
so there is no permanent website credential to synchronize. It runs every day,
uploads the JSON edition as an audit artifact, and publishes it to ATTENUA
through the authenticated ingest route.

## Tests

```bash
pytest
```

Every source's parsing logic is unit tested against fixture data (HTML
tables, JSON payloads, RSS/Atom XML) — no network access required. A few
integration-style tests use `responses` to mock HTTP end-to-end for a
source's `collect()`. `tests/sources/test_base.py` covers the shared
caching/robots/rate-limit machinery once so individual source tests don't
have to.

## Notes on the sources' own rules

Every source sets a descriptive User-Agent including `contact_email` and
respects `robots.txt` (a couple of API-style hosts — `data.sec.gov`,
`api.github.com`, `hn.algolia.com`, `api.gdeltproject.org`, `rdap.org`, and
the other documented JSON APIs — are exempted, since they're APIs rather than
crawlable pages, and their
`robots.txt` files don't cover them meaningfully). Per-domain rate limits are
configurable under `rate_limits`; keep them polite for hosts you query often.
