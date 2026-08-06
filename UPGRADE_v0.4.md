# Upgrade to v0.4 — Signal Classification

Version 0.4 separates true spinout evidence from ordinary semiconductor news.

## Main changes

- Financial vehicles such as trusts, fixed-income products, credit funds, and partnerships are rejected before scoring.
- Strong semiconductor terms are separated from contextual terms such as `core`, `power`, and `logic`.
- A spinout item requires formation/personnel-change language plus meaningful domain evidence or a watchlist-person match.
- Ordinary technical stories appear under **Industry intelligence**, not the Spinout Discovery Inbox.
- LinkedIn checks are split into **signal-driven** names and a five-person **routine founder rotation**.
- Conservative headline extraction can turn clear startup announcements into named emerging entities.

## Upgrade

```bash
git checkout spinout-radar-v0.4
python -m pip install -e ".[dev]"
python -m pytest -q
radar reset-data --yes
radar run 2>&1 | tee run-v0.4.log
```
