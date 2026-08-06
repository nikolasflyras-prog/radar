# Upgrade to Spinout Radar v0.5

Version 0.5 expands source coverage while retaining v0.4's conservative signal classification.

## Changes

- New `gdelt` collector for high-intent public-news discovery.
- Watchlist-person and watched-employer search rotation.
- Public watchlist-mention section in the digest.
- GitHub identity-candidate discovery and confirmation commands.
- Current official ISSCC, Hot Chips, DAC, and IEDM program pages.
- Scheduled workflow now runs tests before collection.
- Package version updated to `0.5.0`.

## Upgrade commands

```bash
git checkout main
git pull
python -m pip install -e ".[dev]"
python -m pytest -q
radar reset-data --yes
radar run 2>&1 | tee run-v0.5.log
radar stats
```

The reset is recommended because earlier databases may contain classifications created before the new source and watchlist rules.

## Optional focused runs

```bash
radar run --source gdelt
radar run --source github
radar run --source conferences
radar github-candidates
```
