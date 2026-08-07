from digger.sources.sec_edgar import is_deal_relevant, parse_hit


def test_parse_hit_builds_archive_url():
    hit = {
        "_id": "0001193125-24-012345:0001193125-24-012345-index.htm",
        "_source": {
            "root_form": "8-K", "file_date": "2024-03-01",
            "display_names": ["Acme Corp (0000123456)"], "items": ["1.01", "9.01"],
            "ciks": ["0000123456"],
        },
    }
    parsed = parse_hit(hit)
    assert parsed["form"] == "8-K"
    assert parsed["items"] == ["1.01", "9.01"]
    assert parsed["url"] == "https://www.sec.gov/Archives/edgar/data/123456/000119312524012345/0001193125-24-012345-index.htm"


def test_is_deal_relevant_requires_deal_items_on_8k():
    relevant = {"form": "8-K", "items": ["1.01"]}
    irrelevant = {"form": "8-K", "items": ["5.02"]}
    no_items_listed = {"form": "8-K", "items": []}
    assert is_deal_relevant(relevant) is True
    assert is_deal_relevant(irrelevant) is False
    assert is_deal_relevant(no_items_listed) is True


def test_is_deal_relevant_true_for_merger_forms():
    assert is_deal_relevant({"form": "S-4", "items": []}) is True
    assert is_deal_relevant({"form": "DEFM14A", "items": []}) is True
    assert is_deal_relevant({"form": "10-K", "items": []}) is False
