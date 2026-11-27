"""Production-scope selection and native, read-only Jira adapter contracts."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "jira" / "rhdh-bug-triage" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bugtriage.jira import (  # noqa: E402
    JiraAdapterError,
    export_from_acli,
    load_tickets_from_acli,
    parse_acli_json,
    search_acli,
    view_acli,
)
from bugtriage.model import (  # noqa: E402
    as_text,
    extract_issues,
    load_export,
    normalize_export,
    normalize_issue,
    verified_support_cases,
)
from bugtriage.selection import (  # noqa: E402
    Control,
    SelectionConfig,
    exclusion_reason,
    select_sample,
)

AS_OF = datetime(2026, 11, 9, tzinfo=timezone.utc)


def issue(key="RHDHBUGS-1", **fields):
    return {
        "key": key,
        "fields": {
            "summary": "Install fails",
            "description": "A specific failure",
            "created": "2023-01-01T00:00:00Z",
            "status": {"name": "Backlog", "statusCategory": {"name": "To Do"}},
            "labels": [],
            "versions": [{"name": "1.5.0"}],
            "issuelinks": [],
            **fields,
        },
    }


def select(records, **config):
    return select_sample(
        [normalize_issue(record) for record in records],
        SelectionConfig(current_release="2.1.0", **config),
        AS_OF,
    )


@pytest.mark.parametrize("release", ["", "latest", "2.1.x", "2.1.0-rc.1"])
def test_aged_scope_requires_unambiguous_release_even_for_empty_input(release):
    with pytest.raises(ValueError, match="current_release"):
        select_sample([], SelectionConfig(current_release=release), AS_OF)


@pytest.mark.parametrize(
    ("versions", "reason"),
    [
        ([], "missing"),
        (None, "missing"),
        ([{"name": "2.1.0"}], "not older"),
        ([{"name": "2.2.0"}], "not older"),
        ([{"name": "1.0.0"}, {"name": "2.1"}], "not older"),
        ([{"name": "1.0.0"}, {"name": "3.0.0"}], "not older"),
        ([{"name": "1.x"}], "ambiguous"),
        ([{"name": "1.0.0"}, {}], "ambiguous"),
        ([{"id": "1234"}], "ambiguous"),
        ([1], "ambiguous"),
    ],
)
def test_aged_scope_excludes_missing_ambiguous_equal_or_newer_versions(versions, reason):
    selected, excluded, eligible = select([issue(versions=versions)])
    assert selected == []
    assert eligible == 0
    assert reason in excluded[0]["reason"]


def test_every_affects_version_must_be_older_with_numeric_not_lexical_comparison():
    selected, excluded, _ = select([issue(versions=[{"name": "v1.10"}, {"name": "2.0.99"}])])
    assert [item.ticket.key for item in selected] == ["RHDHBUGS-1"]
    assert excluded == []


def test_aged_scope_uses_creation_age_and_includes_exactly_ninety_days():
    records = [
        issue(
            "RHDHBUGS-90",
            created=(AS_OF - timedelta(days=90)).isoformat(),
            updated=AS_OF.isoformat(),
        ),
        issue("RHDHBUGS-89", created=(AS_OF - timedelta(days=89)).isoformat()),
        issue("RHDHBUGS-88", created="unreadable"),
    ]
    selected, excluded, _ = select(records)
    assert [item.ticket.key for item in selected] == ["RHDHBUGS-90"]
    assert "younger" in next(item["reason"] for item in excluded if item["key"] == "RHDHBUGS-89")
    assert "unreadable" in next(item["reason"] for item in excluded if item["key"] == "RHDHBUGS-88")


def test_aged_scope_cannot_be_reduced_below_ninety_days():
    with pytest.raises(ValueError, match="at least 90"):
        select([], aged_days=30)


def test_all_open_bypasses_only_age_and_affects_filters():
    records = [
        issue("RHDHBUGS-1", versions=[], created=AS_OF.isoformat()),
        issue("RHDHBUGS-2", versions=[{"name": "future"}], created="unreadable"),
        issue("RHDHBUGS-3", labels=["RHDH-Customer"]),
        issue("RHDHBUGS-4", status={"name": "Custom final", "statusCategory": {"name": "Done"}}),
        issue("OTHER-5"),
    ]
    selected, excluded, eligible = select_sample(
        [normalize_issue(record) for record in records],
        SelectionConfig(scope="all-open", all_tickets=True),
        AS_OF,
    )
    assert {item.ticket.key for item in selected} == {"RHDHBUGS-1", "RHDHBUGS-2", "RHDHBUGS-3"}
    assert {item.kind for item in selected} == {"all-open"}
    assert eligible == 3
    reasons = {item["key"]: item["reason"] for item in excluded}
    assert "RHDHBUGS-3" not in reasons
    assert "done" in reasons["RHDHBUGS-4"]
    assert "project" in reasons["OTHER-5"]


def test_exclusion_reason_accepts_main_orchestrator_arguments():
    ticket = normalize_issue(issue(versions=[]))
    assert "missing" in exclusion_reason(ticket, AS_OF, 90, "2.1.0", "aged")
    assert exclusion_reason(ticket, AS_OF, 90, "", "all-open") == ""


def test_all_open_does_not_treat_an_unfetched_status_as_open():
    selected, excluded, eligible = select([issue(status=None)], scope="all-open")
    assert selected == []
    assert eligible == 0
    assert "cannot establish an open issue" in excluded[0]["reason"]


def test_all_tickets_is_stable_and_sampling_remains_stratified():
    records = [
        issue(f"RHDHBUGS-{number}", team="Install" if number < 8 else "UI")
        for number in range(1, 11)
    ]
    first, _, eligible = select(records, size=1, all_tickets=True)
    second, _, _ = select(list(reversed(records)), size=1, all_tickets=True)
    assert [item.ticket.key for item in first] == [item.ticket.key for item in second]
    assert len(first) == eligible == 10
    sampled, _, _ = select(records, size=2)
    assert len(sampled) == 2
    assert {item.stratum for item in sampled} == {"Install", "UI"}


def test_controls_bypass_age_versions_but_not_done_or_project_filters():
    records = [
        issue("RHDHBUGS-1", versions=[], created=AS_OF.isoformat()),
        issue("RHDHBUGS-2", labels=["RHDH-Customer"]),
        issue("RHDHBUGS-3", status={"name": "Closed"}),
        issue("OTHER-4"),
    ]
    selected, excluded, _ = select(
        records, size=0, controls=[Control(record["key"]) for record in records]
    )
    assert [item.ticket.key for item in selected] == ["RHDHBUGS-1", "RHDHBUGS-2"]
    assert selected[0].kind == "control"
    assert len(excluded) == 2


def test_rest_status_category_is_authoritative_over_flat_category_alias():
    ticket = normalize_issue(
        issue(
            status={
                "name": "Custom final",
                "statusCategory": {"name": "Done"},
                "category": {"name": "To Do"},
            }
        )
    )
    assert ticket.is_done
    assert ticket.status_category == "Done"


def test_adf_hidden_links_and_customer_references_survive_normalization():
    description = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Case",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": "https://redhat.atlassian.net/browse/ACCOUNT-7"},
                            }
                        ],
                    },
                    {"type": "inlineCard", "attrs": {"url": "https://github.com/org/repo/pull/42"}},
                ],
            }
        ],
    }
    ticket = normalize_issue(issue(description=description))
    assert "ACCOUNT-7" in ticket.description
    assert "https://github.com/org/repo/pull/42" in ticket.description
    assert ticket.pr_urls == ["https://github.com/org/repo/pull/42"]
    assert "text:ACCOUNT-7" in ticket.customer_signals


@pytest.mark.parametrize(
    "value",
    [
        {"id": "21", "value": "Example customer"},
        {"id": "21", "name": "Example customer"},
        {"id": "21"},
        {"nested": {"name": "Example customer"}},
    ],
)
def test_customer_custom_field_objects_cannot_disappear(value):
    record = issue(customfield_42=value)
    record["names"] = {"customfield_42": "Customers"}
    ticket = normalize_issue(record)
    assert "field:Customers" in ticket.customer_signals
    assert ticket.customer_fields_read == ["Customers"]
    assert ticket.unmapped_custom_fields == []


@pytest.mark.parametrize("value", [None, "", [], {}, 0, False, "0", {"value": ""}])
def test_empty_customer_fields_are_not_customer_signals(value):
    ticket = normalize_issue(issue(**{"Customer Name": value}))
    assert ticket.customer_signals == []
    assert ticket.customer_fields_read == ["Customer Name"]


def test_custom_field_text_retains_name_and_value_objects():
    assert "Customer" in as_text({"id": "123", "name": "Customer"})
    assert "Customer" in as_text({"id": "123", "value": {"name": "Customer"}})


@pytest.mark.parametrize("mapping_key", ["names", "fieldNames"])
def test_export_field_mapping_is_carried_to_each_ticket(tmp_path, mapping_key):
    document = {
        mapping_key: {"customfield_42": "Customer Impact"},
        "issues": [issue(customfield_42={"id": "9", "name": "High"})],
    }
    path = tmp_path / "issues.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert "field:Customer Impact" in load_export(str(path))[0].customer_signals


def test_conflicting_name_maps_do_not_erase_a_known_customer_field():
    document = {
        "names": {"customfield_42": "Customers"},
        "fieldNames": {"customfield_42": "Unrelated"},
        "issues": [
            {**issue(customfield_42={"id": "3"}), "fieldNames": {"customfield_42": "Other"}}
        ],
    }
    ticket = normalize_export(document, {"customfield_42": "Other"})[0]
    assert "field:Customers" in ticket.customer_signals


def test_customer_coverage_remains_unknown_and_observed_unmapped_fields_are_reported():
    record = issue(customfield_99={"id": "4"})
    record["customerFieldsComplete"] = True  # An unverified export claim is not a field catalogue.
    ticket = normalize_issue(record)
    assert ticket.customer_signals == []
    assert ticket.customer_fields_read == []
    assert not ticket.customer_fields_complete
    assert ticket.unmapped_custom_fields == ["customfield_99"]
    assert any("coverage" in gap for gap in ticket.read_gaps)
    assert any("customfield_99" in gap for gap in ticket.read_gaps)


def test_explicit_empty_comments_are_distinct_from_unfetched_history():
    fetched = normalize_issue(issue(comments=[]))
    missing = normalize_issue(issue())
    assert fetched.comments_fetched
    assert not missing.comments_fetched
    assert fetched.comments == missing.comments == []
    assert not fetched.comments_complete  # A bare export list has no pagination provenance.
    assert not missing.comments_complete
    assert any("fetched but" in gap for gap in fetched.read_gaps)
    assert any("not fetched" in gap for gap in missing.read_gaps)
    assert normalize_issue(issue(comment={"comments": [], "total": 0})).comments_complete


def test_incomplete_comment_marker_wins_over_matching_totals():
    ticket = normalize_issue(issue(comment={"comments": [], "total": 0}, commentsComplete=False))
    assert ticket.comments_fetched
    assert not ticket.comments_complete


@pytest.mark.parametrize(
    "metadata",
    [
        {"isLast": False},
        {"hasMore": True},
        {"nextPageToken": "more"},
        {"commentsComplete": False},
        {"startAt": 1},
    ],
)
def test_contradictory_comment_pagination_is_not_certified_complete(metadata):
    ticket = normalize_issue(issue(comment={"comments": [], "total": 0, **metadata}))
    assert ticket.comments_fetched
    assert not ticket.comments_complete


def test_null_comment_alias_does_not_hide_an_explicit_comments_list():
    ticket = normalize_issue(issue(comment=None, comments=[], commentsComplete=True))
    assert ticket.comments_fetched
    assert ticket.comments_complete


@pytest.mark.parametrize(
    "document",
    [
        [issue(), None],
        {"issues": [issue(), "broken"]},
        {"issues": [issue(), {}]},
        {"issues": [issue(), {"key": "../RHDHBUGS-2"}]},
        {"issues": [issue(), {"key": "RHDHBUGS-2", "fields": []}]},
        {"issues": [issue()], "total": 2},
        {"issues": [issue()], "startAt": 10},
        {"issues": [issue()], "isLast": False},
        {"issues": [issue()], "nextPageToken": "more"},
        {"issues": [issue()], "errors": ["not authorized"]},
        {"issues": [{**issue(), "error": "permission denied"}]},
        {"issues": [], "success": False},
        {"issues": "broken"},
        {"issues": [issue(), issue()]},
        {"issues": [issue()], "total": "20"},
        {"issues": [issue()], "total": -1},
        {"issues": [issue()], "startAt": False},
    ],
)
def test_malformed_or_partial_issue_exports_are_not_silently_accepted(document):
    with pytest.raises(ValueError):
        extract_issues(document)
    with pytest.raises(JiraAdapterError):
        parse_acli_json(json.dumps(document))


@pytest.mark.parametrize(
    "key", ["../RHDHBUGS-1", "RHDHBUGS-1/../../x", "RHDHBUGS-1\n", "1234", "--help"]
)
def test_invalid_issue_keys_fail_before_any_command_or_path_use(monkeypatch, key):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid key reached subprocess")

    monkeypatch.setattr(subprocess, "run", unexpected)
    with pytest.raises(JiraAdapterError, match="key"):
        view_acli(key)
    with pytest.raises(ValueError, match="key"):
        normalize_issue({"key": key})


@pytest.mark.parametrize(
    "wrap",
    [
        lambda record: record,
        lambda record: [record],
        lambda record: {"issues": [record]},
        lambda record: {"results": [record]},
        lambda record: {"items": [record]},
    ],
)
def test_acli_parser_accepts_full_view_objects_lists_and_envelopes(wrap):
    record = issue()
    assert parse_acli_json(json.dumps(wrap(record))) == [record]


@pytest.mark.parametrize("stdout", ["", "not json", '{"message": "forbidden"}'])
def test_empty_invalid_or_failed_command_output_is_not_an_empty_success(stdout):
    with pytest.raises(JiraAdapterError):
        parse_acli_json(stdout)


def result(args, document, stderr="", returncode=0):
    return subprocess.CompletedProcess(args, returncode, json.dumps(document), stderr)


def test_search_requests_supported_summary_fields_and_paginates(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return result(args, [{"key": "RHDHBUGS-1", "summary": "Search-only"}])

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert search_acli("project = RHDHBUGS")[0]["key"] == "RHDHBUGS-1"
    command = calls[0]
    assert command[:4] == ["acli", "jira", "workitem", "search"]
    assert command[command.index("--fields") + 1] == "key,summary"
    assert "*all" not in command
    assert "--paginate" in command


def test_explicit_search_limit_is_recorded_not_mistaken_for_full_pagination(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return result(args, {"issues": [{"key": "RHDHBUGS-1"}], "total": 20})

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert len(search_acli("project = RHDHBUGS", limit=1)) == 1
    assert "--paginate" not in calls[0]
    assert calls[0][-2:] == ["--limit", "1"]


def test_fetch_hydrates_every_search_hit_and_exports_full_read_provenance(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[3] == "search":
            return result(
                args,
                {
                    "names": {"customfield_42": "Customers"},
                    "issues": [
                        {"key": "RHDHBUGS-1", "summary": "Search-only"},
                        {"key": "RHDHBUGS-2", "summary": "Search-only"},
                    ],
                },
            )
        if args[3] == "view":
            return result(args, issue(args[4], customfield_42={"id": "21", "name": "Customer"}))
        assert args[3:5] == ["comment", "list"]
        assert "--paginate" in args
        return result(args, [{"id": "100", "body": "Read the current history."}])

    monkeypatch.setattr(subprocess, "run", fake_run)
    document = export_from_acli("project = RHDHBUGS")
    assert [record["key"] for record in document["issues"]] == ["RHDHBUGS-1", "RHDHBUGS-2"]
    assert {args[4] for args in calls if args[3] == "view"} == {"RHDHBUGS-1", "RHDHBUGS-2"}
    assert all("*all" in args for args in calls if args[3] == "view")
    assert document["fieldNames"] == {"customfield_42": "Customers"}
    provenance = document["provenance"]
    assert provenance["searchCount"] == provenance["fullReadCount"] == 2
    assert provenance["commentsCompleteCount"] == 2
    assert provenance["searchComplete"] is True
    assert provenance["customerFieldCoverage"] == "mapped-fields-complete"
    assert provenance["customerFieldsCompleteCount"] == 2
    tickets = normalize_export(json.loads(json.dumps(document)))
    assert all(ticket.summary == "Install fails" for ticket in tickets)
    assert all(ticket.comments_complete and ticket.comments_fetched for ticket in tickets)
    assert all("field:Customers" in ticket.customer_signals for ticket in tickets)


def test_load_tickets_uses_full_view_not_search_projection(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[3] == "search":
            return result(args, [{"key": "RHDHBUGS-1", "summary": "Search-only"}])
        assert args[3] == "view"
        return result(args, issue(comment={"comments": [], "total": 0}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    tickets = load_tickets_from_acli("project = RHDHBUGS")
    assert tickets[0].summary == "Install fails"
    assert tickets[0].comments_complete
    assert len(calls) == 2  # A proven complete REST page needs no extra comment read.


def test_paginated_comment_read_does_not_override_evidence_of_partial_history(monkeypatch):
    def fake_run(args, **kwargs):
        if args[3] == "search":
            return result(args, [{"key": "RHDHBUGS-1"}])
        if args[3] == "view":
            return result(args, issue(comment={"comments": [], "total": 1}))
        return result(args, {"comments": [{"id": "1", "body": "One of two"}], "total": 2})

    monkeypatch.setattr(subprocess, "run", fake_run)
    document = export_from_acli("project = RHDHBUGS")
    ticket = normalize_export(document)[0]
    assert ticket.comments_fetched
    assert not ticket.comments_complete
    assert len(ticket.comments) == 1
    assert document["provenance"]["commentsCompleteCount"] == 0


@pytest.mark.parametrize(
    ("returncode", "stderr"), [(1, "permission denied"), (0, "partial read failed")]
)
def test_failed_or_stderr_reads_are_errors_not_partial_success(monkeypatch, returncode, stderr):
    def fake_run(args, **kwargs):
        return result(args, [{"key": "RHDHBUGS-1"}], stderr=stderr, returncode=returncode)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(JiraAdapterError, match=stderr):
        export_from_acli("project = RHDHBUGS")


@pytest.mark.parametrize(
    "record",
    [
        {"key": "RHDHBUGS-1", "summary": "Search-only"},
        issue("RHDHBUGS-2"),
        {"issues": [issue(), issue("RHDHBUGS-2")]},
    ],
)
def test_view_refuses_partial_wrong_or_multiple_issue_reads(monkeypatch, record):
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: result(args, record))
    with pytest.raises(JiraAdapterError):
        view_acli("RHDHBUGS-1")


def test_full_issue_failure_aborts_export_instead_of_dropping_that_ticket(monkeypatch):
    def fake_run(args, **kwargs):
        if args[3] == "search":
            return result(args, [{"key": "RHDHBUGS-1"}, {"key": "RHDHBUGS-2"}])
        if args[4] == "RHDHBUGS-2":
            return result(args, {}, stderr="one full read failed", returncode=1)
        return result(args, issue(comment={"comments": [], "total": 0}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(JiraAdapterError, match="one full read failed"):
        export_from_acli("project = RHDHBUGS")


@pytest.mark.parametrize(
    "comments", [None, {"errorMessages": ["denied"]}, [{"id": "1"}], ["broken"]]
)
def test_comment_read_failures_cannot_become_complete_empty_history(monkeypatch, comments):
    def fake_run(args, **kwargs):
        if args[3] == "search":
            return result(args, [{"key": "RHDHBUGS-1"}])
        if args[3] == "view":
            return result(args, issue())
        return result(args, comments)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(JiraAdapterError, match="comment"):
        export_from_acli("project = RHDHBUGS")


def test_duplicate_search_rows_are_not_counted_as_successful_full_reads(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: result(args, [issue(), issue()]))
    with pytest.raises(JiraAdapterError, match="duplicate"):
        export_from_acli("project = RHDHBUGS")


def test_partial_comment_hydration_preserves_original_page_customer_references(monkeypatch):
    def fake_run(args, **kwargs):
        if args[3] == "search":
            return result(args, [{"key": "RHDHBUGS-1"}])
        if args[3] == "view":
            return result(
                args,
                issue(
                    comment={
                        "comments": [{"id": "old", "body": "See RHDHSUPP-42"}],
                        "total": 2,
                    }
                ),
            )
        return result(args, {"comments": [{"id": "new", "body": "Other page"}], "total": 2})

    monkeypatch.setattr(subprocess, "run", fake_run)
    ticket = load_tickets_from_acli("project = RHDHBUGS")[0]
    assert not ticket.comments_complete
    assert {comment.id for comment in ticket.comments} == {"old", "new"}
    assert "text:RHDHSUPP-42" in ticket.customer_signals


def test_matching_comment_ids_are_not_duplicated_during_hydration(monkeypatch):
    def fake_run(args, **kwargs):
        if args[3] == "search":
            return result(args, [{"key": "RHDHBUGS-1"}])
        if args[3] == "view":
            return result(
                args,
                issue(
                    comment={
                        "comments": [{"id": "1", "body": "Old text"}],
                        "total": 2,
                    }
                ),
            )
        return result(args, [{"id": "1", "body": "Fresh text"}, {"id": "2", "body": "Second"}])

    monkeypatch.setattr(subprocess, "run", fake_run)
    ticket = load_tickets_from_acli("project = RHDHBUGS")[0]
    assert ticket.comments_complete
    assert len(ticket.comments) == 2
    assert ticket.comments[0].body == "Fresh text"


def test_full_reads_use_at_most_four_concurrent_native_commands(monkeypatch):
    barrier = threading.Barrier(4)
    lock = threading.Lock()
    active = 0
    maximum = 0

    def fake_run(args, **kwargs):
        nonlocal active, maximum
        if args[3] == "search":
            return result(args, [{"key": f"RHDHBUGS-{number}"} for number in range(1, 9)])
        assert args[3] == "view"
        with lock:
            active += 1
            maximum = max(maximum, active)
        barrier.wait(timeout=5)
        with lock:
            active -= 1
        return result(args, issue(args[4], comment={"comments": [], "total": 0}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert len(export_from_acli("project = RHDHBUGS")["issues"]) == 8
    assert maximum == 4


@pytest.mark.parametrize("missing", [None, "customfield_99", "labels", "issuelinks"])
def test_customer_coverage_requires_all_known_mapped_fields_and_signal_collections(missing):
    mapped = {"customfield_42": "Customer Name", "customfield_99": "Customer Impact"}
    record = issue(customfield_42=None, customfield_99=None)
    if missing:
        record["fields"].pop(missing)
    ticket = normalize_issue(record, mapped)
    assert ticket.customer_fields_complete is (missing is None)
    assert ticket.customer_signals == []
    assert any("coverage" in gap for gap in ticket.read_gaps) is (missing is not None)
    if missing == "customfield_99":
        assert any("not fetched: customfield_99" in gap for gap in ticket.read_gaps)


def test_direct_customer_name_does_not_replace_absent_mapped_fields():
    ticket = normalize_issue(
        issue(**{"Customer Name": None}),
        {"customfield_42": "Customer Name", "customfield_99": "Customer Impact"},
    )
    assert not ticket.customer_fields_complete


@pytest.mark.parametrize("fields_present", [True, False])
def test_host_field_catalogue_supports_names_null_without_inventing_fields(
    monkeypatch, fields_present
):
    mapped = {"customfield_42": "Customer Name", "customfield_99": "Customer Impact"}

    def fake_run(args, **kwargs):
        if args[3] == "search":
            return result(args, [{"key": "RHDHBUGS-1"}])
        record = issue(comment={"comments": [], "total": 0}, customfield_42=None)
        record["names"] = None
        if fields_present:
            record["fields"]["customfield_99"] = None
        return result(args, record)

    monkeypatch.setattr(subprocess, "run", fake_run)
    document = export_from_acli("project = RHDHBUGS", field_names=mapped)
    assert document["fieldNames"] == mapped
    assert ("customfield_99" in document["issues"][0]["fields"]) is fields_present
    assert document["provenance"]["customerFieldsCompleteCount"] == int(fields_present)
    assert normalize_export(document)[0].customer_fields_complete is fields_present
    assert document["provenance"]["customerFieldCoverage"] == (
        "mapped-fields-complete" if fields_present else "unknown"
    )


@pytest.mark.parametrize("type_field", ["type", "linktype"])
@pytest.mark.parametrize("direction", ["outwardIssue", "inwardIssue"])
def test_account_relationship_to_another_project_is_a_native_customer_signal(type_field, direction):
    record = issue(
        issuelinks=[
            {
                type_field: {"name": "Account"},
                direction: {"key": "CIPOE-203270", "fields": {"summary": "Account record"}},
            }
        ]
    )
    ticket = normalize_issue(record)
    assert "link:Account:CIPOE-203270" in ticket.customer_signals
    assert not exclusion_reason(ticket, AS_OF, 90, "2.1.0", "all-open")


@pytest.mark.parametrize(
    "name",
    [
        "Account Number",
        "Account",
        "Support Case Reference",
        "SFDC Cases Counter",
        "SFDC Cases Links",
        "SFDC Cases Open",
    ],
)
def test_account_and_support_field_names_are_recognized_without_tenant_id_constants(name):
    ticket = normalize_issue(
        issue(customfield_42={"id": "9", "value": "Populated"}),
        {
            "customfield_42": name,
        },
    )
    assert f"field:{name}" in ticket.customer_signals


def test_populated_qe_impact_is_a_screening_precaution_not_a_claim_of_a_customer_case():
    ticket = normalize_issue(
        issue(customfield_42={"value": "QE Confirmed"}),
        {
            "customfield_42": "Customer Impact",
        },
    )
    assert ticket.customer_signals == ["field:Customer Impact"]
    reason = exclusion_reason(ticket, AS_OF, 90, "2.1.0")
    assert not reason


def test_native_relationship_takes_precedence_over_a_populated_impact_precaution():
    ticket = normalize_issue(
        issue(
            customfield_42={"value": "QE Confirmed"},
            issuelinks=[{"type": {"name": "Account"}, "outwardIssue": {"key": "CIPOE-203270"}}],
        ),
        {"customfield_42": "Customer Impact"},
    )
    reason = exclusion_reason(ticket, AS_OF, 90, "2.1.0")
    assert not reason
    assert "link:Account:CIPOE-203270" in ticket.customer_signals


def test_missing_global_account_and_support_fields_stay_unknown_not_fetched_and_empty():
    record = issue(customfield_42=None)
    ticket = normalize_issue(
        record,
        {
            "customfield_42": "Customer Name",
            "customfield_43": "Account Number",
            "customfield_44": "Support Case Reference",
        },
    )
    assert not ticket.customer_fields_complete
    assert ticket.customer_signals == []
    assert "customfield_43" not in record["fields"]
    assert "customfield_44" not in record["fields"]
    assert any("customfield_43, customfield_44" in gap for gap in ticket.read_gaps)


def test_generic_customer_wording_in_security_docs_does_not_invent_customer_signals():
    record = issue(
        description="Security documentation explains how a customer configures authentication."
    )
    selected, excluded, _ = select([record])
    assert selected[0].ticket.customer_signals == []
    assert excluded == []


@pytest.mark.parametrize(
    "ref",
    [
        "RHDHBUGS-1519",
        "https://redhat.atlassian.net/browse/RHDHBUGS-1519?focusedCommentId=123",
    ],
)
def test_cited_host_customer_review_is_additive_and_never_completes_field_reads(ref):
    record = issue("RHDHBUGS-1519", description="See RHDHSUPP-42 for the original case.")
    record["triageCustomerSignals"] = [
        {
            "ref": ref,
            "reason": "Explicit customer POC in comment",
        }
    ]
    ticket = normalize_issue(record)
    assert "text:RHDHSUPP-42" in ticket.customer_signals
    assert f"host:{ref}:Explicit customer POC in comment" in ticket.customer_signals
    assert not ticket.customer_fields_complete
    selected, excluded, _ = select([record])
    assert [item.ticket.key for item in selected] == ["RHDHBUGS-1519"]
    assert not excluded


def test_cited_host_review_can_screen_a_semantic_poc_without_a_native_signal():
    record = issue("RHDHBUGS-1519", description="Failure found during a customer POC.")
    assert normalize_issue(record).customer_signals == []
    record["triageCustomerSignals"] = [
        {
            "ref": "https://redhat.atlassian.net/browse/RHDHBUGS-1519?focusedCommentId=123",
            "reason": "Explicit customer POC in comment",
        }
    ]
    ticket = normalize_issue(record)
    assert len(ticket.customer_signals) == 1
    assert "host:" in ticket.customer_signals[0]


@pytest.mark.parametrize(
    "declaration",
    [
        None,
        True,
        "customer",
        ["customer"],
        [{}],
        [{"ref": "RHDHBUGS-1519"}],
        [{"ref": "RHDHBUGS-1519", "reason": "  "}],
        [{"ref": "RHDHBUGS-1519", "reason": 42}],
        [{"ref": "../RHDHBUGS-1519", "reason": "Customer POC"}],
        [{"ref": "http://example.test/case", "reason": "Customer POC"}],
        [{"ref": "https:///case", "reason": "Customer POC"}],
        [{"ref": "https://user:secret@example.test/case", "reason": "Customer POC"}],
        [{"ref": "https://example.test/invalid ref", "reason": "Customer POC"}],
        [{"ref": "https://example.test:bad/case", "reason": "Customer POC"}],
        [{"ref": "https://example.test/\x00", "reason": "Customer POC"}],
    ],
)
def test_malformed_host_customer_declarations_are_rejected_not_silently_ignored(declaration):
    record = issue()
    record["triageCustomerSignals"] = declaration
    with pytest.raises(ValueError, match="triageCustomerSignals"):
        normalize_issue(record)


def test_empty_host_customer_declarations_do_not_clear_native_customer_signals():
    record = issue(labels=["RHDH-Customer"])
    record["triageCustomerSignals"] = []
    assert "label:RHDH-Customer" in normalize_issue(record).customer_signals


def test_support_coordination_requires_a_structured_case_reference():
    portal = "https://access.redhat.com/support/cases/123456"
    ticket = normalize_issue(
        issue(
            labels=["RHDH-Customer"],
            description="A different report mentioned RHDHSUPP-19",
            customfield_11=[portal, "RHDHSUPP-22"],
            issuelinks=[
                {"type": {"name": "Related"}, "outwardIssue": {"key": "RHDHSUPP-22"}},
                {"type": {"name": "Account"}, "outwardIssue": {"key": "ACCOUNT-33"}},
            ],
        ),
        {"customfield_11": "Support Case Reference"},
    )
    assert verified_support_cases(ticket.customer_signals) == ["RHDHSUPP-22", portal]
    other = normalize_issue(issue(description="See RHDHSUPP-19", labels=["RHDH-Customer"]))
    assert other.customer_signals
    assert verified_support_cases(other.customer_signals) == []
