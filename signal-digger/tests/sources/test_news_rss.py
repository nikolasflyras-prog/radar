import responses

from digger.cache import ResponseCache
from digger.models import Target
from digger.sources.news_rss import NewsRssSource, target_feeds

from datetime import datetime, timezone

FEED_XML = f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Acme to acquire Widgets Co</title>
  <link>https://feed.example.com/1</link>
  <summary>Definitive agreement signed for the acquisition</summary>
  <pubDate>{datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate>
</item>
<item>
  <title>Unrelated company news</title>
  <link>https://feed.example.com/2</link>
  <summary>A completely different topic with no relevant company mentioned</summary>
  <pubDate>{datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate>
</item>
</channel></rss>
"""


def test_target_feeds_appends_google_news():
    feeds = target_feeds([{"name": "TechCrunch", "url": "https://techcrunch.com/feed/"}], "Acme")
    names = [f["name"] for f in feeds]
    assert "TechCrunch" in names
    assert "Google News" in names
    assert "Acme" in [f["url"] for f in feeds if f["name"] == "Google News"][0]


@responses.activate
def test_collect_filters_unrelated_entries_from_configured_feeds(tmp_path):
    responses.add(responses.GET, "https://feed.example.com/rss", body=FEED_XML, status=200)
    responses.add(responses.GET, "https://news.google.com/rss/search", body="<rss><channel></channel></rss>", status=200)
    config = {
        "contact_email": "t@example.com", "timeout_seconds": 5, "rate_limit_seconds": 0, "rate_limits": {},
        "cache": {"ttl_hours": {"default": 0}}, "lookback_days": 3650,
        "rss_feeds": [{"name": "ExampleFeed", "url": "https://feed.example.com/rss", "respect_robots": False}],
    }
    source = NewsRssSource(config, cache=ResponseCache(tmp_path / "cache.db"), use_cache=False)
    result = source.collect(Target(mode="company", query="Acme"))

    titles = {f.title for f in result.findings}
    assert "Acme to acquire Widgets Co" in titles
    assert "Unrelated company news" not in titles
    ma_finding = next(f for f in result.findings if f.title == "Acme to acquire Widgets Co")
    assert ma_finding.category == "ma_deal"
