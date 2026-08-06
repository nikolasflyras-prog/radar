from __future__ import annotations

from datetime import datetime, timedelta, timezone
from .base import BaseCollector
from ..models import CollectorResult, Signal


class GitHubWatchCollector(BaseCollector):
    name = "github"
    def __init__(self, config, db=None):
        super().__init__(config, db)
        token = config.get("tokens", {}).get("github")
        if token: self.session.headers.update({"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"})

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("github", 14)))
        keywords = [x.casefold() for x in self.config["keywords"].get("terms", [])]
        for person in self.config.get("people", []):
            for username in person.get("github_usernames", []):
                try:
                    profile = self.get(f"https://api.github.com/users/{username}", respect_robots=False).json()
                    orgs = self.get(f"https://api.github.com/users/{username}/orgs?per_page=100", respect_robots=False).json()
                    events = self.get(f"https://api.github.com/users/{username}/events/public?per_page=100", respect_robots=False).json()
                except Exception as exc: result.errors.append(f"{username}: {exc}"); continue
                result.rows_fetched += 1 + len(orgs) + len(events)
                if any(k in f"{profile.get('company','')} {profile.get('bio','')}".casefold() for k in keywords):
                    result.signals.append(Signal(source=self.name, signal_type="github_profile_change", entity_name=profile.get("company"),
                        person_names=[person["name"]], observed_at=self.utcnow(), title=f"GitHub profile signal: {username}",
                        url=profile.get("html_url"), summary=f"Company: {profile.get('company')}; bio: {profile.get('bio')}",
                        raw={k: profile.get(k) for k in ("login","company","bio","blog","updated_at")}, source_key=f"gh-profile:{username}:{profile.get('updated_at')}"))
                for org in orgs:
                    if any(k in f"{org.get('login','')} {org.get('description','')}".casefold() for k in keywords):
                        result.signals.append(Signal(source=self.name, signal_type="github_keyword_org", entity_name=org.get("login"),
                            person_names=[person["name"]], observed_at=self.utcnow(), title=f"{username} belongs to {org.get('login')}",
                            url=org.get("html_url"), summary="Domain-keyword GitHub organization linked to a watchlist person", raw=org,
                            source_key=f"gh-org:{username}:{org.get('id')}"))
                recent = [e for e in events if datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) >= since]
                baseline = max(1, int(person.get("github_weekly_baseline", 0)))
                if baseline >= 5 and len(recent) <= max(1, baseline // 4):
                    result.signals.append(Signal(source=self.name, signal_type="github_activity_drop", person_names=[person["name"]],
                        observed_at=self.utcnow(), title=f"Public GitHub activity drop: {username}", url=profile.get("html_url"),
                        summary=f"{len(recent)} recent public events versus configured baseline {baseline}",
                        raw={"recent": len(recent), "baseline": baseline}, source_key=f"gh-drop:{username}:{self.utcnow():%G-%V}"))
        return result

