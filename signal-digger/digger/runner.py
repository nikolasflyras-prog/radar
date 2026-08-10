from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .cache import ResponseCache
from .models import SourceResult, Target
from .sources import SOURCES


def collect_sources(
    target: Target,
    config: dict,
    selected: set[str] | None = None,
    *,
    cache_root: Path | None = None,
    use_cache: bool = True,
) -> list[SourceResult]:
    selected = selected or set(SOURCES)
    unknown = selected - set(SOURCES)
    if unknown:
        raise ValueError(f"Unknown source(s): {', '.join(sorted(unknown))}")
    root = cache_root or Path.cwd()
    cache = ResponseCache(root / config.get("cache", {}).get("path", "data/cache.db"))
    instances = [cls(config, cache=cache, use_cache=use_cache) for name, cls in SOURCES.items() if name in selected]
    results: list[SourceResult] = []
    with ThreadPoolExecutor(max_workers=min(8, len(instances) or 1)) as pool:
        futures = {pool.submit(source.run, target): source.name for source in instances}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(SourceResult(source=name, errors=[f"{type(exc).__name__}: {exc}"]))
    return sorted(results, key=lambda item: item.source)
