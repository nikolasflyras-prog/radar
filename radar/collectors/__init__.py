from .sec_form_d import SecFormDCollector
from .uspto_assignments import UsptoAssignmentsCollector
from .github_watch import GitHubWatchCollector
from .hn_algolia import HNAlgoliaCollector
from .news_rss import NewsRSSCollector
from .gdelt_news import GdeltNewsCollector
from .conference_programs import ConferenceProgramsCollector
from .incorporation_records import IncorporationRecordsCollector
from .domains_whois import DomainsRdapCollector

COLLECTORS = {
    "edgar": SecFormDCollector, "uspto": UsptoAssignmentsCollector,
    "github": GitHubWatchCollector, "hn": HNAlgoliaCollector,
    "rss": NewsRSSCollector, "gdelt": GdeltNewsCollector, "conferences": ConferenceProgramsCollector,
    "incorporation": IncorporationRecordsCollector, "domains": DomainsRdapCollector,
}
