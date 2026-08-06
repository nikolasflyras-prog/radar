from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import quote_plus

from .base import BaseCollector
from ..db import normalize_name
from ..models import CollectorResult, Signal
from ..relevance import classify_public_signal, matched_terms


class GitHubWatchCollector(BaseCollector):
    name = "github"

    def __init__(self, config, db=None):
        super().__init__(config, db)
        token = config.get("tokens", {}).get("github")
        self.has_token = bool(token)
        if token:
            self.session.headers.update({
                "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28",
                "Accept": "application/vnd.github+json",
            })

    def _monitor_handle(self, result: CollectorResult, person: dict, username: str, since: datetime) -> None:
        try:
            profile = self.get(f"https://api.github.com/users/{username}", respect_robots=False).json()
            orgs = self.get(f"https://api.github.com/users/{username}/orgs?per_page=100", respect_robots=False).json()
            events = self.get(f"https://api.github.com/users/{username}/events/public?per_page=100", respect_robots=False).json()
        except Exception as exc:
            result.errors.append(f"{username}: {exc}")
            return
        result.rows_fetched += 1 + len(orgs) + len(events)
        blob = f"{profile.get('company', '')} {profile.get('bio', '')} {profile.get('blog', '')}"
        classification = classify_public_signal(blob, self.config.get("keywords", {}), [person["name"]])
        old_employer = person.get("last_known_employer") or ""
        current_company = str(profile.get("company") or "").lstrip("@").strip()
        changed_company = bool(current_company and old_employer and normalize_name(current_company) != normalize_name(old_employer))
        if changed_company or classification.category in {"spinout", "industry"}:
            result.signals.append(Signal(
                source=self.name, signal_type="github_profile_change",
                entity_name=current_company if changed_company else None,
                person_names=[person["name"]], observed_at=self.utcnow(),
                title=f"GitHub profile signal: {username}", url=profile.get("html_url"),
                summary=(
                    f"Company: {current_company or 'blank'}; prior employer: {old_employer or 'unknown'}; "
                    f"bio: {profile.get('bio') or 'blank'}"
                ),
                raw={
                    **{k: profile.get(k) for k in ("login", "name", "company", "bio", "blog", "updated_at")},
                    "classification": classification.category, "company_changed": changed_company,
                    "matched_strong_terms": list(classification.strong_terms),
                    "startup_language": list(classification.startup_terms),
                },
                base_weight=12 if changed_company else 6,
                source_key=f"gh-profile:{username}:{profile.get('updated_at')}",
            ))
        keywords = self.config.get("keywords", {}).get("strong_terms", [])
        for org in orgs:
            login = org.get("login") or ""
            if matched_terms(login, keywords):
                result.signals.append(Signal(
                    source=self.name, signal_type="github_keyword_org", entity_name=login,
                    person_names=[person["name"]], observed_at=self.utcnow(),
                    title=f"{username} belongs to {login}", url=f"https://github.com/{login}",
                    summary="Domain-keyword GitHub organization linked to a watchlist person",
                    raw=org, source_key=f"gh-org:{username}:{org.get('id')}",
                ))
        recent = [e for e in events if datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) >= since]
        baseline = max(1, int(person.get("github_weekly_baseline", 0)))
        if baseline >= 5 and len(recent) <= max(1, baseline // 4):
            result.signals.append(Signal(
                source=self.name, signal_type="github_activity_drop", person_names=[person["name"]],
                observed_at=self.utcnow(), title=f"Public GitHub activity drop: {username}",
                url=profile.get("html_url"),
                summary=f"{len(recent)} recent public events versus configured baseline {baseline}",
                raw={"recent": len(recent), "baseline": baseline},
                source_key=f"gh-drop:{username}:{self.utcnow():%G-%V}",
            ))

    def _discovery_people(self) -> list[dict]:
        cfg = self.config.get("github_discovery", {})
        if not cfg.get("enabled", True):
            return []
        people = [p for p in self.config.get("people", []) if not p.get("github_usernames")]
        priority = [p for p in people if "prior_founder" in p.get("specialty_tags", [])] or people
        requested = int(cfg.get("people_per_run", 20))
        limit = requested if self.has_token else min(requested, 5)
        if not priority or limit <= 0:
            return []
        week = self.utcnow().isocalendar().week
        offset = (week * limit) % len(priority)
        return (priority[offset:] + priority[:offset])[:limit]

    def _discover_handle(self, result: CollectorResult, person: dict) -> None:
        query = quote_plus(f'{person["name"]} in:fullname')
        try:
            search = self.get(f"https://api.github.com/search/users?q={query}&per_page=5", respect_robots=False).json()
        except Exception as exc:
            result.errors.append(f"discover {person['name']}: {exc}")
            return
        items = search.get("items", []) if isinstance(search, dict) else []
        result.rows_fetched += len(items)
        old_employer = person.get("last_known_employer") or ""
        keyword_cfg = self.config.get("keywords", {})
        threshold = int(self.config.get("github_discovery", {}).get("minimum_confidence", 5))
        for item in items:
            try:
                profile = self.get(item["url"], respect_robots=False).json()
            except Exception as exc:
                result.errors.append(f"profile {item.get('login')}: {exc}")
                continue
            result.rows_fetched += 1
            profile_name = profile.get("name") or ""
            if normalize_name(profile_name) != normalize_name(person["name"]):
                continue
            blob = f"{profile.get('company', '')} {profile.get('bio', '')} {profile.get('blog', '')}"
            confidence = 3
            reasons = ["exact profile-name match"]
            if old_employer and normalize_name(old_employer) in normalize_name(profile.get("company") or ""):
                confidence += 4
                reasons.append("company matches last known employer")
            domain_matches = matched_terms(blob, keyword_cfg.get("strong_terms", []))
            if domain_matches:
                confidence += 2
                reasons.append("semiconductor terms in profile")
            if profile.get("blog"):
                confidence += 1
            if confidence < threshold:
                continue
            current_company = str(profile.get("company") or "").lstrip("@").strip()
            entity = None
            if current_company and old_employer and normalize_name(current_company) != normalize_name(old_employer):
                entity = current_company
            result.signals.append(Signal(
                source=self.name, signal_type="github_identity_candidate", entity_name=entity,
                person_names=[person["name"]], observed_at=self.utcnow(),
                title=f"Possible GitHub identity: {person['name']} → @{profile.get('login')}",
                url=profile.get("html_url"), summary=f"Confidence {confidence}/10; " + "; ".join(reasons),
                raw={
                    "candidate_username": profile.get("login"), "confidence": confidence,
                    "reasons": reasons, "profile_name": profile_name, "company": profile.get("company"),
                    "bio": profile.get("bio"), "blog": profile.get("blog"),
                },
                base_weight=2,
                source_key=f"gh-identity:{normalize_name(person['name'])}:{profile.get('login')}",
            ))
            break

    def collect(self, since: datetime | None = None) -> CollectorResult:
        result = CollectorResult(source=self.name)
        since = since or self.utcnow() - timedelta(days=int(self.config.get("lookback_days", {}).get("github", 14)))
        for person in self.config.get("people", []):
            for username in person.get("github_usernames", []):
                self._monitor_handle(result, person, username, since)
        for person in self._discovery_people():
            self._discover_handle(result, person)
        return result
