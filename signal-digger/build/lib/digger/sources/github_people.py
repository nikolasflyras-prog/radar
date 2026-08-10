from __future__ import annotations

from datetime import datetime

from ..models import Mode, SourceResult, Target
from ..textutil import mentions_target, normalize
from .base import BaseSource


def company_change(profile: dict, prior_employer: str) -> tuple[str, bool]:
    """Return (current company field, whether it looks like a change from the
    person's previously-known employer). Pure function, unit-testable."""
    current = str(profile.get("company") or "").lstrip("@").strip()
    changed = bool(current and prior_employer and normalize(current) != normalize(prior_employer))
    return current, changed


class GitHubPeopleSource(BaseSource):
    """GitHub public activity for named people: profile bio/company changes and
    public org membership. Requires `known_people` in config (name, optional
    github_usernames, optional employer) — without a roster there is nothing to
    watch, so the source skips cleanly rather than erroring."""

    name = "github_people"
    modes: tuple[Mode, ...] = ("company", "person")

    def __init__(self, config, cache=None, use_cache=True):
        super().__init__(config, cache, use_cache)
        token = config.get("tokens", {}).get("github")
        if token:
            self.session.headers.update({
                "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28",
                "Accept": "application/vnd.github+json",
            })

    def _people_for(self, target: Target) -> list[dict]:
        people = self.config.get("known_people", [])
        if target.mode == "person":
            matches = [p for p in people if normalize(p.get("name", "")) == normalize(target.query)]
            return matches or [{"name": target.query, "github_usernames": []}]
        return [p for p in people if mentions_target(p.get("employer") or "", target.query)]

    def _search_handle(self, name: str) -> str | None:
        try:
            payload = self.fetch_json(
                "https://api.github.com/search/users", params={"q": f"{name} in:fullname", "per_page": 5},
                respect_robots=False,
            )
        except Exception:
            return None
        items = payload.get("items") or []
        return items[0]["login"] if items else None

    def _inspect(self, result: SourceResult, person: dict, username: str) -> None:
        try:
            profile = self.fetch_json(f"https://api.github.com/users/{username}", respect_robots=False)
            orgs = self.fetch_json(f"https://api.github.com/users/{username}/orgs?per_page=100", respect_robots=False)
        except Exception as exc:
            result.errors.append(f"{username}: {exc}")
            return
        result.rows_fetched += 1 + len(orgs)
        updated = profile.get("updated_at")
        try:
            observed = datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else self.utcnow()
        except ValueError:
            observed = self.utcnow()
        current_company, changed = company_change(profile, person.get("employer") or "")
        result.findings.append(self.finding(
            source=self.name, category="people_movement",
            title=f"GitHub profile: {profile.get('name') or username} (@{username})",
            observed_at=observed, url=profile.get("html_url"),
            summary=f"Company field: {current_company or 'blank'}; bio: {profile.get('bio') or 'blank'}",
            people=[person["name"]], entities=[current_company] if current_company else [],
            raw={k: profile.get(k) for k in ("login", "name", "company", "bio", "blog", "updated_at")},
            quiet=changed, quiet_reason="Company field changed with no matching announcement found yet" if changed else "",
            dedupe_key=f"gh-profile:{username}:{updated}",
        ))
        for org in orgs:
            login = org.get("login") or ""
            result.findings.append(self.finding(
                source=self.name, category="people_movement",
                title=f"@{username} is a public member of GitHub org {login}",
                observed_at=observed, url=f"https://github.com/{login}",
                summary="Public GitHub organization membership",
                people=[person["name"]], entities=[login] if login else [],
                raw=dict(org),
                dedupe_key=f"gh-org:{username}:{org.get('id')}",
            ))

    def collect(self, target: Target) -> SourceResult:
        result = SourceResult(source=self.name)
        people = self._people_for(target)
        if not people:
            result.skipped_reason = "no known_people configured for this target"
            return result
        for person in people:
            handles = list(person.get("github_usernames") or [])
            if not handles:
                candidate = self._search_handle(person["name"])
                handles = [candidate] if candidate else []
            for username in handles:
                self._inspect(result, person, username)
        return result
