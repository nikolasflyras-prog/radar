# Signal Digger

On-demand deep research CLI. Point it at a company, a sector, or a person; it
fans out across public sources in parallel and compiles one report — M&A
activity, staff movement, and the quiet stuff that doesn't make the news.
Every run writes both a Markdown report and a matching self-contained HTML
version (light/dark aware, no external assets — open it straight in a
browser).

This is a one-shot tool, not a monitor. There's no watchlist, no cadence, no
scoring tier. You run it, it researches, it writes a report. Re-running on the
same target within a source's cache TTL just replays the cached raw response
instead of hitting the network again — the product is the report, not an
accumulating database.

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
| `news_gdelt` | all | GDELT DOC 2.0 news search. Runs one deal-language query and one broad recency query, then buckets every article into `ma_deal` or `general_signal` by whether it actually contains M&A vocabulary. |
| `news_rss` | all | RSS search: any feeds under `rss_feeds`, plus an automatic Google News RSS query for the target (works with zero configuration). Same M&A/general bucketing as `news_gdelt`. |
| `github_people` | company, person | Public GitHub activity for people listed in `known_people`: profile bio/company-field changes and public org membership. Without a `known_people` entry matching the target, this source skips cleanly (not an error). |
| `hackernews` | all | Hacker News via the Algolia search API: story mentions, "Who's hiring?" thread comments naming the target (flagged quiet — self-identification with no announcement), and other comment mentions. |
| `job_boards` | company, sector | Greenhouse and Lever public job-board APIs. Flags `"Founding [Role]"` postings directly (an early signal on its own) and hiring surges versus the previous cached posting count. Board slugs come from `job_boards.slug_overrides`, falling back to a best-effort guess from the company name. |
| `domain_whois` | all | RDAP (WHOIS successor) lookups on domains guessed from the target name (`.com`, `.ai`, `.io`, `.co`). Flags recent registrations and recent registrant/registrar changes — always marked quiet, since these essentially never come with a press release. |
| `conference_programs` | all | Scans configured conference program/speaker-list pages (`conferences`) for the target's name and, when found, a nearby `"Name (Affiliation)"` pair. Flags an affiliation that differs from a `known_people` entry's recorded employer. |

`job_boards`, `sec_edgar`, `ftc_hsr`, and `uspto_assignments` only run for
company/sector targets — they're inherently per-employer, not per-person.
`github_people` only runs for company/person targets, since it needs a named
roster to check.

## Caching

Raw responses (not parsed findings) are cached in SQLite at `data/cache.db`,
keyed by `(source, url, params)` with a per-source TTL from
`cache.ttl_hours` in the config. `--no-cache` bypasses it entirely for one
run without deleting anything. There's no accumulating findings database —
each run recomputes and re-emits everything fresh from whatever's cached or
freshly fetched.

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
`api.github.com`, `hn.algolia.com`, `api.gdeltproject.org`, `rdap.org` — are
exempted, since they're JSON APIs rather than crawlable pages, and their
`robots.txt` files don't cover them meaningfully). Per-domain rate limits are
configurable under `rate_limits`; keep them polite for hosts you query often.
