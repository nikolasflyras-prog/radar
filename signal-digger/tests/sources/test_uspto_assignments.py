import responses

from digger.cache import ResponseCache
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


def test_assignment_rows_unwraps_official_patent_file_wrapper_response():
    payload = {"patentFileWrapperDataBag": [{"applicationNumberText": "18123456", "assignmentBag": [{
        "assignorName": "Acme Inc", "assigneeName": "Buyer Co", "recordedDate": "2026-08-01",
        "documentIdentifier": "700011234",
    }]}]}
    rows = assignment_rows(payload)
    assert len(rows) == 1
    assert parse_assignment_doc(rows[0], "Acme")["reel_frame"] == "700011234"


def test_source_skips_cleanly_without_required_odp_key():
    source = UsptoAssignmentsSource({"tokens": {}}, cache=None, use_cache=False)
    result = source.collect(Target(mode="company", query="Acme"))
    assert result.status == "skipped"
    assert "USPTO_API_KEY" in result.skipped_reason


@responses.activate
def test_collect_uses_embedded_assignments_without_detail_request(tmp_path):
    responses.add(
        responses.GET,
        UsptoAssignmentsSource.search_endpoint,
        json={"patentFileWrapperDataBag": [{
            "applicationNumberText": "18/123,456",
            "assignmentBag": [{
                "assignorBag": [{"assignorName": "Acme Inc"}],
                "assigneeBag": [{"assigneeName": "Buyer Co"}],
                "assignmentReceivedDate": "2026-08-01",
                "reelAndFrameNumber": "70001/1234",
            }],
        }]},
        status=200,
    )
    source = UsptoAssignmentsSource(
        {"tokens": {"uspto": "test-key"}, "lookback_days": 90, "rate_limit_seconds": 0,
         "cache": {"ttl_hours": {"default": 0}}},
        cache=ResponseCache(tmp_path / "cache.db"), use_cache=False,
    )
    result = source.collect(Target(mode="company", query="Acme"))
    assert len(result.findings) == 1
    assert len(responses.calls) == 1


@responses.activate
def test_collect_stops_detail_requests_after_first_403(tmp_path):
    responses.add(
        responses.GET,
        UsptoAssignmentsSource.search_endpoint,
        json={"patentFileWrapperDataBag": [
            {"applicationNumberText": "18/111,111"},
            {"applicationNumberText": "18/222,222"},
        ]},
        status=200,
    )
    responses.add(
        responses.GET,
        UsptoAssignmentsSource.assignment_endpoint.format(application_number="18111111"),
        json={"message": "Forbidden"}, status=403,
    )
    source = UsptoAssignmentsSource(
        {"tokens": {"uspto": "test-key"}, "lookback_days": 90, "rate_limit_seconds": 0,
         "cache": {"ttl_hours": {"default": 0}}},
        cache=ResponseCache(tmp_path / "cache.db"), use_cache=False,
    )
    result = source.collect(Target(mode="company", query="Acme"))
    assert len(responses.calls) == 2
    assert any("skipped remaining detail requests" in error for error in result.errors)
