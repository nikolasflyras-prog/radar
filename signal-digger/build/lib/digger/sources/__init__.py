from __future__ import annotations

from .base import BaseSource
from .conference_programs import ConferenceProgramsSource
from .domain_whois import DomainWhoisSource
from .ftc_hsr import FtcHsrSource
from .github_people import GitHubPeopleSource
from .hackernews import HackerNewsSource
from .job_boards import JobBoardsSource
from .news_gdelt import NewsGdeltSource
from .news_rss import NewsRssSource
from .sec_edgar import SecEdgarSource
from .uspto_assignments import UsptoAssignmentsSource

# Registering a new source is one module implementing BaseSource plus one line here.
SOURCES: dict[str, type[BaseSource]] = {
    "sec_edgar": SecEdgarSource,
    "ftc_hsr": FtcHsrSource,
    "uspto_assignments": UsptoAssignmentsSource,
    "news_gdelt": NewsGdeltSource,
    "news_rss": NewsRssSource,
    "github_people": GitHubPeopleSource,
    "hackernews": HackerNewsSource,
    "job_boards": JobBoardsSource,
    "domain_whois": DomainWhoisSource,
    "conference_programs": ConferenceProgramsSource,
}
