from datetime import datetime, timedelta, timezone

import responses

from radar.collectors.google_news_rss import GoogleNewsRSSCollector


def _feed(items: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Google News</title>
{items}
</channel>
</rss>"""


def _item(title: str, link: str, description: str, pub_date: str, publisher: str = "Example Times") -> str:
    return f"""<item>
<title>{title}</title>
<link>{link}</link>
<guid>{link}</guid>
<pubDate>{pub_date}</pubDate>
<description>{description}</description>
<source url="https://example.com">{publisher}</source>
</item>"""


def _cfg():
    now = datetime.now(timezone.utc)
    return {
        "contact_email": "test@example.com",
        "rate_limit_seconds": 0,
        "timeout_seconds": 30,
        "rate_limits": {},
        "lookback_days": {"googlenews": 30},
        "keywords": {
            "strong_terms": ["chiplet", "silicon photonics", "semiconductor"],
            "contextual_terms": ["core", "logic"],
            "startup_language": ["stealth", "founded", "has left"],
            "startup_weak_language": ["startup"],
            "departure_language": ["has left", "departed"],
            "movement_language": ["has left", "departed", "former"],
            "formation_queries": ["semiconductor startup founder"],
            "news_query_domain_terms": [],
        },
        "people": [
            {"name": "Jane Chen", "known_aliases": [], "last_known_employer": "Marvell", "specialty_tags": ["prior_founder"]},
        ],
        "orgs": [],
        "news_search": {"max_employer_queries": 0, "watchlist_people_queries": 0, "max_queries": 1},
        "_now": now,
    }


@responses.activate
def test_google_news_collector_flags_own_employer_departure():
    cfg = _cfg()
    responses.add(responses.GET, "https://news.google.com/robots.txt", body="User-agent: *\nAllow: /", status=200)
    recent = (cfg["_now"] - timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    feed = _feed(_item(
        "Jane Chen has left Marvell to build a stealth chiplet startup",
        "https://example.com/story1",
        "Jane Chen has left Marvell to build a stealth chiplet startup, sources say.",
        recent,
    ))
    responses.add(responses.GET, "https://news.google.com/rss/search", body=feed, status=200,
                   content_type="application/rss+xml")

    collector = GoogleNewsRSSCollector(cfg)
    result = collector.collect(since=cfg["_now"] - timedelta(days=30))

    assert not result.errors
    assert len(result.signals) == 1
    signal = result.signals[0]
    assert signal.signal_type == "news_departure_stealth"
    assert signal.person_names == ["Jane Chen"]
    assert signal.raw["own_employer_departure"] == ["Jane Chen"]


@responses.activate
def test_google_news_collector_skips_irrelevant_items():
    cfg = _cfg()
    responses.add(responses.GET, "https://news.google.com/robots.txt", body="User-agent: *\nAllow: /", status=200)
    recent = (cfg["_now"] - timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    feed = _feed(_item(
        "Local weather forecast calls for rain this weekend",
        "https://example.com/story2",
        "Meteorologists expect a wet weekend with periodic showers across the region.",
        recent,
    ))
    responses.add(responses.GET, "https://news.google.com/rss/search", body=feed, status=200,
                   content_type="application/rss+xml")

    collector = GoogleNewsRSSCollector(cfg)
    result = collector.collect(since=cfg["_now"] - timedelta(days=30))

    assert not result.errors
    assert result.signals == []


@responses.activate
def test_google_news_collector_fails_soft_when_robots_disallow():
    cfg = _cfg()
    responses.add(responses.GET, "https://news.google.com/robots.txt", body="User-agent: *\nDisallow: /", status=200)

    collector = GoogleNewsRSSCollector(cfg)
    result = collector.collect(since=cfg["_now"] - timedelta(days=30))

    assert result.signals == []
    assert result.errors
