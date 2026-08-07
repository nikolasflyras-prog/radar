from digger.sources.uspto_assignments import parse_assignment_doc


def test_parse_assignment_doc_matches_assignee():
    doc = {
        "assignors": [{"name": "Big Corp"}], "assignees": [{"name": "Acme Inc"}],
        "recordedDate": "2026-02-01", "reelFrame": "12345/6789",
        "assignmentUrl": "https://example.com/assign/1", "correspondentName": "Law Firm LLP",
    }
    parsed = parse_assignment_doc(doc, "Acme")
    assert parsed is not None
    assert parsed["assignees"] == ["Acme Inc"]
    assert parsed["reel_frame"] == "12345/6789"


def test_parse_assignment_doc_matches_assignor_too():
    doc = {"assignors": [{"name": "Acme Inc"}], "assignees": [{"name": "Third Party"}], "recordedDate": "2026-01-01"}
    assert parse_assignment_doc(doc, "Acme") is not None


def test_parse_assignment_doc_returns_none_when_unrelated():
    doc = {"assignors": [{"name": "Other Corp"}], "assignees": [{"name": "Third Party"}], "recordedDate": "2026-01-01"}
    assert parse_assignment_doc(doc, "Acme") is None


def test_parse_assignment_doc_handles_plain_string_names():
    doc = {"assignorNames": ["Acme Inc"], "assigneeNames": ["Buyer Co"], "recorded_date": "2026-01-01", "id": "abc"}
    parsed = parse_assignment_doc(doc, "Acme")
    assert parsed is not None
    assert parsed["reel_frame"] == "abc"
