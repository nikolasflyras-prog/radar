from digger.sources import SOURCES
from digger.sources.base import BaseSource


def test_registry_has_expected_sources():
    expected = {
        "sec_edgar", "ftc_hsr", "uspto_assignments", "news_gdelt", "news_rss",
        "github_people", "hackernews", "job_boards", "domain_whois", "conference_programs",
    }
    assert set(SOURCES) == expected


def test_every_registered_source_is_a_base_source_subclass():
    for cls in SOURCES.values():
        assert issubclass(cls, BaseSource)


def test_every_source_declares_at_least_one_mode():
    for cls in SOURCES.values():
        assert len(cls.modes) >= 1
        assert set(cls.modes) <= {"company", "sector", "person"}
