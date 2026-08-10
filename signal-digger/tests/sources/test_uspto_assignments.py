from digger.models import Target
from digger.sources.uspto_assignments import (
    UsptoAssignmentsSource,
    application_number,
    assignment_rows,
    parse_assignment_doc,
)


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


def test_parse_assignment_doc_handles_odp_bags():
    doc = {
        "assignorBag": [{"assignorName": "Acme Inc"}],
        "assigneeBag": [{"assigneeName": "Buyer Co"}],
        "assignmentReceivedDate": "2026-08-01",
        "reelAndFrameNumber": "70001/1234",
    }
    parsed = parse_assignment_doc(doc, "Acme")
    assert parsed is not None
    assert parsed["assignors"] == ["Acme Inc"]
    assert parsed["reel_frame"] == "70001/1234"


def test_odp_response_helpers():
    row = {"applicationMetaData": {"applicationIdentification": {"applicationNumberText": "18/123,456"}}}
    assert application_number(row) == "18123456"
    assert assignment_rows({"assignmentBag": [{"id": "a"}]}) == [{"id": "a"}]


def test_source_skips_cleanly_without_required_odp_key():
    source = UsptoAssignmentsSource({"tokens": {}}, cache=None, use_cache=False)
    result = source.collect(Target(mode="company", query="Acme"))
    assert result.status == "skipped"
    assert "USPTO_API_KEY" in result.skipped_reason
