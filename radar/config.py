from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_config(root: Path) -> dict[str, Any]:
    cfg_dir = root / "config"
    cfg = load_yaml(cfg_dir / "config.yaml")
    cfg["root"] = str(root)
    cfg["keywords"] = load_yaml(cfg_dir / "keywords.yaml")
    cfg["people"] = load_yaml(cfg_dir / "watchlist_people.yaml").get("people", [])
    cfg["orgs"] = load_yaml(cfg_dir / "watchlist_orgs.yaml").get("organizations", [])
    cfg["conferences"] = load_yaml(cfg_dir / "conferences.yaml").get("conferences", [])
    cfg.setdefault("tokens", {})
    cfg["tokens"]["github"] = os.getenv("GITHUB_TOKEN", cfg["tokens"].get("github"))
    cfg["tokens"]["opencorporates"] = os.getenv("OPENCORPORATES_TOKEN", cfg["tokens"].get("opencorporates"))
    return cfg

