from digger.sources.ftc_hsr import parse_listing_html

FIXTURE_HTML = """
<table>
<tr><th>Grant Date</th><th>Parties</th><th>Transaction Number</th></tr>
<tr><td>03/01/2026</td><td><a href="/notice/1">Acme Corp; Widgets Inc</a></td><td>20261234</td></tr>
<tr><td>02/15/2026</td><td>Other Company; Unrelated LLC</td><td>20261100</td></tr>
<tr><td>01/20/2026</td><td>Acme Holdings; Third Party</td><td>20260999</td></tr>
</table>
"""


def test_parse_listing_html_filters_to_query_matches():
    rows = parse_listing_html(FIXTURE_HTML, "Acme")
    assert len(rows) == 2
    assert rows[0]["parties"] == "Acme Corp; Widgets Inc"
    assert rows[0]["transaction_number"] == "20261234"
    assert rows[0]["url"] == "/notice/1"


def test_parse_listing_html_no_matches_returns_empty():
    assert parse_listing_html(FIXTURE_HTML, "Nonexistent Co") == []


def test_parse_listing_html_ignores_header_row():
    rows = parse_listing_html(FIXTURE_HTML, "Grant")
    assert rows == []
