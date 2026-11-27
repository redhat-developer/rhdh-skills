"""End-to-end comment previews, coverage, and the no-external-effects boundary."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/jira/rhdh-bug-triage/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bugtriage import cli, forge  # noqa: E402
from bugtriage import jira as jira_adapter  # noqa: E402
from bugtriage.evaluate import evaluate, load_truth  # noqa: E402
from bugtriage.model import load_export  # noqa: E402
from bugtriage.policy import Packet, next_step_kind, parse_assessment  # noqa: E402
from bugtriage.policy import evaluate as evaluate_packet  # noqa: E402
from bugtriage.run import (  # noqa: E402
    RunConfig,
    RunError,
    build_sample_manifest,
    default_jql,
    run,
)
from bugtriage.selection import Control, SelectionConfig  # noqa: E402

RELEASE = "2.1.0"
RELEASE_RECORD = (
    "https://docs.redhat.com/en/documentation/red_hat_developer_hub/2.1/html/release_notes"
)
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


@pytest.fixture
def inputs(tmp_path):
    issue = {
        "key": "RHDHBUGS-101",
        "fields": {
            "summary": "Catalog refresh loses the active filter",
            "description": "Selecting a filter then refreshing loses the selected filter.",
            "status": {"name": "New", "statusCategory": {"name": "To Do"}},
            "issuetype": {"name": "Bug"},
            "created": "2025-01-01T00:00:00Z",
            "updated": "2026-11-01T00:00:00Z",
            "versions": [{"name": "1.9.0"}],
            "labels": [],
            "issuelinks": [],
            "comment": {"comments": [], "total": 0, "startAt": 0},
            "customfield_12345": None,
        },
    }
    export = tmp_path / "issues.json"
    export.write_text(
        json.dumps({"issues": [issue], "fieldNames": {"customfield_12345": "Customer Name"}})
    )
    sample = build_sample_manifest(
        load_export(str(export)),
        SelectionConfig(current_release=RELEASE, all_tickets=True),
        NOW,
        default_jql(90),
    )
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps(sample))
    assessments = tmp_path / "assessments"
    assessments.mkdir()
    (assessments / "RHDHBUGS-101.json").write_text(
        json.dumps(
            {
                "key": "RHDHBUGS-101",
                "verdict": "unclear",
                "evidence": [
                    {
                        "type": "jira",
                        "ref": "RHDHBUGS-101",
                        "strength": "direct",
                        "why": "The original report describes filter loss; the current release was not reproduced.",
                    }
                ],
                "review": {"independentPasses": 2, "agree": True},
            }
        )
    )
    return RunConfig(
        input_path=str(export),
        sample_path=str(sample_path),
        assessments_dir=str(assessments),
        output_dir=str(tmp_path / "review"),
        current_release=RELEASE,
        release_evidence=RELEASE_RECORD,
        as_of="2026-11-17",
    )


def test_end_to_end_uncertainty_has_exact_comment_not_an_empty_closure_report(inputs, monkeypatch):
    def unexpected_external_call(*args, **kwargs):
        pytest.fail(f"offline run attempted an external process: {args}")

    monkeypatch.setattr(subprocess, "run", unexpected_external_call)
    result = run(inputs)
    packet = result.packets[0]
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert packet.proposed_comment
    assert packet.comment_plan["status"] == "propose"
    comment = (result.output_dir / "01-triage" / "comments" / f"{packet.key}.md").read_text()
    assert comment.strip() == packet.proposed_comment
    saved = json.loads((result.output_dir / "01-triage" / "audit" / "packets.json").read_text())
    assert saved["packets"][0]["proposedComment"] == packet.proposed_comment
    assert result.manifest["counts"]["draftComments"] == 1
    assert result.manifest["counts"]["closeProposals"] == 0
    assert result.manifest["writes"] == []
    assert result.manifest["inputSha256"]["export"]


@pytest.mark.parametrize("scope", ["aged", "all-open"])
def test_sample_size_counts_every_reviewed_bug_not_only_aged_ones(inputs, scope):
    """``sampleSize`` describes the run, not the name of the scope.

    ``Selection.kind`` carries the scope string, so counting only ``kind ==
    "aged"`` recorded zero reviewed bugs for an ``--scope all-open`` run while
    the packets correctly held every bug.
    """
    sample = build_sample_manifest(
        load_export(inputs.input_path),
        SelectionConfig(current_release=RELEASE, all_tickets=True, scope=scope),
        NOW,
        default_jql(90, scope),
    )
    Path(inputs.sample_path).write_text(json.dumps(sample))
    inputs.scope = scope

    result = run(inputs)

    assert result.manifest["sampleSize"] == 1
    assert result.manifest["sampleSize"] == result.manifest["counts"]["packets"]


def test_missing_assessment_directory_is_an_error_not_successful_zero_results(inputs):
    inputs.assessments_dir += "-typo"
    with pytest.raises(RunError, match="assessment directory"):
        run(inputs)
    assert not Path(inputs.output_dir).exists()


def test_missing_one_assessment_blocks_incomplete_triage(inputs):
    Path(inputs.assessments_dir, "RHDHBUGS-101.json").unlink()
    with pytest.raises(RunError, match="missing assessments"):
        run(inputs)


def test_unfilled_template_is_not_a_completed_investigation(inputs):
    Path(inputs.assessments_dir, "RHDHBUGS-101.json").write_text(
        json.dumps({"key": "RHDHBUGS-101", "verdict": "", "evidence": []})
    )
    with pytest.raises(RunError, match="unfilled template"):
        run(inputs)


def test_required_investigation_rejects_unclear_placeholder_before_output(inputs):
    inputs.require_investigation = True
    with pytest.raises(RunError, match="investigation incomplete"):
        run(inputs)
    assert not Path(inputs.output_dir).exists()


def test_required_investigation_preserves_blocked_check_without_certifying_completion(inputs):
    path = Path(inputs.assessments_dir, "RHDHBUGS-101.json")
    document = json.loads(path.read_text())
    document["investigation"] = {
        "status": "blocked",
        "release": RELEASE,
        "scope": "The reported catalog filter refresh scenario.",
        "mechanism": "The report omits which filter and catalog request lose state.",
        "requirements": [
            {
                "statement": "The selected filter survives refresh.",
                "result": "unknown",
                "observed": "No original request trace or filter value is attached.",
                "method": "report",
                "refs": ["RHDHBUGS-101"],
            }
        ],
        "blocker": "Identify the original filter value and an existing refresh request trace.",
    }
    path.write_text(json.dumps(document))
    inputs.require_investigation = True
    result = run(inputs)
    assert result.manifest["investigationRequired"] is True
    assert result.manifest["investigationStates"] == {
        "completed": 0,
        "blocked": 1,
        "not_recorded": 0,
    }
    assert result.packets[0].to_dict()["investigationOutcome"] == "not_determined"
    assert result.manifest["writes"] == []


@pytest.mark.parametrize("field,value", [("currentRelease", "1.9.0"), ("scope", "all-open")])
def test_saved_sample_cannot_change_scope_or_baseline_silently(inputs, field, value):
    path = Path(inputs.sample_path)
    sample = json.loads(path.read_text())
    sample[field] = value
    path.write_text(json.dumps(sample))
    with pytest.raises(RunError, match="release/scope"):
        run(inputs)


def test_saved_sample_cannot_bypass_current_eligibility(inputs):
    path = Path(inputs.input_path)
    document = json.loads(path.read_text())
    document["issues"][0]["fields"]["versions"] = [{"name": RELEASE}]
    path.write_text(json.dumps(document))
    with pytest.raises(RunError, match="stale|no longer eligible"):
        run(inputs)


def test_empty_saved_sample_cannot_silently_skip_currently_eligible_issue(inputs):
    path = Path(inputs.sample_path)
    sample = json.loads(path.read_text())
    sample["tickets"] = []
    sample["eligibleCount"] = 0
    path.write_text(json.dumps(sample))
    with pytest.raises(RunError, match="eligibility count is stale"):
        run(inputs)


def test_age_threshold_cannot_be_changed_after_selection(inputs):
    inputs.aged_days = 30
    with pytest.raises(RunError, match="age threshold"):
        run(inputs)


@pytest.mark.parametrize(
    "change",
    [{"labels": ["RHDH-Customer"]}, {"status": {"name": "Closed"}}],
)
def test_saved_controls_recheck_customer_and_done_exclusions(inputs, change):
    path = Path(inputs.input_path)
    document = json.loads(path.read_text())
    document["issues"][0]["fields"]["versions"] = []
    path.write_text(json.dumps(document))
    sample = build_sample_manifest(
        load_export(str(path)),
        SelectionConfig(current_release=RELEASE, controls=[Control("RHDHBUGS-101")]),
        NOW,
        default_jql(90),
    )
    Path(inputs.sample_path).write_text(json.dumps(sample))
    assert sample["eligibleCount"] == 0
    document["issues"][0]["fields"].update(change)
    path.write_text(json.dumps(document))
    if "labels" in change:
        run(inputs)
        return
    with pytest.raises(RunError, match="control.*no longer eligible"):
        run(inputs)
    assert not Path(inputs.output_dir).exists()


def test_out_of_scope_controls_cannot_make_partial_selection_complete(inputs):
    path = Path(inputs.input_path)
    document = json.loads(path.read_text())
    for key, versions in [("RHDHBUGS-102", ["1.9.0"]), ("RHDHBUGS-103", [])]:
        item = json.loads(json.dumps(document["issues"][0]))
        item["key"] = key
        item["fields"]["versions"] = [{"name": version} for version in versions]
        document["issues"].append(item)
    path.write_text(json.dumps(document))
    sample = build_sample_manifest(
        load_export(str(path)),
        SelectionConfig(current_release=RELEASE, size=1, controls=[Control("RHDHBUGS-103")]),
        NOW,
        default_jql(90),
    )
    Path(inputs.sample_path).write_text(json.dumps(sample))
    for entry in sample["tickets"]:
        Path(inputs.assessments_dir, entry["key"] + ".json").write_text(
            json.dumps({"key": entry["key"], "verdict": "unclear"})
        )
    result = run(inputs)
    coverage = result.manifest["coverage"]
    assert coverage["selectedIssues"] == coverage["eligibleIssues"] == 2
    assert coverage["selectionComplete"] is False


def test_supplied_sample_bytes_are_hashed_in_run_provenance(inputs):
    import hashlib

    result = run(inputs)
    assert (
        result.manifest["inputSha256"]["sample"]
        == hashlib.sha256(Path(inputs.sample_path).read_bytes()).hexdigest()
    )


def test_second_run_refuses_output_without_modifying_it(inputs):
    result = run(inputs)
    before = {str(p): p.read_bytes() for p in result.output_dir.rglob("*") if p.is_file()}
    with pytest.raises(RunError, match="already exists"):
        run(inputs)
    assert before == {str(p): p.read_bytes() for p in result.output_dir.rglob("*") if p.is_file()}


def test_failed_searches_and_bounded_coverage_survive_into_report(inputs, tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "RHDHBUGS-101.json").write_text(
        json.dumps(
            {
                "key": "RHDHBUGS-101",
                "searchMode": "live",
                "searches": [
                    {
                        "repository": "redhat-developer/rhdh",
                        "status": "error",
                        "error": "rate limited",
                    }
                ],
            }
        )
    )
    inputs.evidence_dir = str(evidence)
    result = run(inputs)
    run_audit = (result.output_dir / "01-triage" / "audit" / "RUN.md").read_text()
    assert "failed" in run_audit
    assert "A failed search is not a zero result." in run_audit
    assert result.manifest["coverage"]["corpusExhaustive"] is False
    assert result.manifest["coverage"]["assessedIssues"] == 1


def test_default_inventory_includes_unlabelled_issues():
    assert "labels" not in default_jql(90)
    assert "created <= -90d" in default_jql(90)
    assert "created <=" not in default_jql(90, "all-open")


@pytest.mark.parametrize("command", ["apply", "post", "close", "fix", "backport"])
def test_no_mutating_cli_operation_exists(command):
    with pytest.raises(SystemExit) as error:
        cli.build_parser().parse_args([command])
    assert error.value.code == 2


def test_strict_evaluation_fails_vacuous_success_and_false_validity():
    truth = {"RHDHBUGS-101": {"verdict": "already_fixed", "duplicateOf": ""}}
    assert not evaluate([], truth).strict_passed
    packet = Packet(
        key="RHDHBUGS-101",
        summary="",
        status="New",
        verdict="still_valid",
        confidence=0.98,
        confidence_basis=[],
        action="comment_only",
        recommended_step="",
        evidence=[],
        duplicate_candidates=[],
    )
    result = evaluate([packet], truth)
    assert result.false_conclusions
    assert not result.strict_passed


def test_malformed_ground_truth_is_not_ignored(tmp_path):
    path = tmp_path / "truth.json"
    path.write_text(json.dumps({"RHDHBUGS-101": {"verdict": "probably fixed"}}))
    with pytest.raises(ValueError, match="unknown truth"):
        load_truth(str(path))


def test_resolved_documentation_with_missing_fix_history_does_not_recheck_persistence(inputs):
    source = "https://example.test/docs/2.1.0/customization"
    document = parse_assessment(
        {
            "key": "RHDHBUGS-101",
            "verdict": "unclear",
            "evidence": [
                {
                    "type": "doc",
                    "ref": source,
                    "strength": "direct",
                    "why": "The requested procedure is present in the released documentation.",
                }
            ],
            "validation": {
                "release": RELEASE,
                "method": "documentation",
                "result": "resolved",
                "summary": "The procedure exists; the original corrective artifact remains unidentified.",
                "refs": [source],
            },
        }
    )
    packet = evaluate_packet(load_export(inputs.input_path)[0], [], document, RELEASE)
    assert packet.verdict == "unclear"
    assert next_step_kind(packet) == "identify_fix_provenance"
    assert source in packet.recommended_step
    assert "not established" in packet.proposed_comment


@pytest.mark.parametrize("term", ["CVE-2025-25290", "SHA-512", "CVE-2025", "OTHER-123"])
def test_key_shaped_terminology_does_not_invent_jira_citations(inputs, term):
    ticket = load_export(inputs.input_path)[0]
    ticket.summary = term
    assessment = parse_assessment(
        {
            "key": ticket.key,
            "verdict": "unclear",
            "evidence": [
                {
                    "type": "jira",
                    "ref": ticket.key,
                    "strength": "direct",
                    "why": f"{term} is terminology, unlike the actual reference RHIDP-123.",
                }
            ],
        }
    )
    comment = evaluate_packet(ticket, [], assessment, RELEASE).proposed_comment
    assert term in comment
    assert f"https://redhat.atlassian.net/browse/{term}" not in comment
    assert "https://redhat.atlassian.net/browse/RHIDP-123" in comment


def test_limited_sources_preserve_validation_boundaries_without_proof_authority(inputs):
    ticket = load_export(inputs.input_path)[0]
    source = "https://example.test/post-ga/source-map.json"
    limitation = "Post-GA source mapping does not identify the shipped image. No benchmark was run."
    assessment = parse_assessment(
        {
            "key": ticket.key,
            "verdict": "unclear",
            "evidence": [{"type": "code", "ref": source, "strength": "limited", "why": limitation}],
            "validation": {
                "method": "code",
                "release": RELEASE,
                "result": "unknown",
                "summary": limitation,
                "refs": [source],
            },
        }
    )
    packet = evaluate_packet(ticket, [], assessment, RELEASE)
    assert not packet.invalid_evidence
    assert packet.evidence[0].strength == "limited"
    assert packet.confidence == 0
    assert packet.verdict == "unclear" and packet.action == "comment_only"
    assert limitation in packet.proposed_comment
    assert "result: unknown" in packet.proposed_comment
    assert source in packet.proposed_comment
    assert "Validation attempt (not proof)" in packet.proposed_comment


def test_uncertain_cited_question_is_preserved_without_becoming_action_execution(inputs):
    ticket = load_export(inputs.input_path)[0]
    source = "https://example.test/pinned/package/read-loop.ts"
    question = (
        "Does a controlled 2.1.0 SQL trace show per-role round trips rather than cached reads?"
    )
    document = {
        "key": ticket.key,
        "verdict": "unclear",
        "evidence": [
            {
                "type": "code",
                "ref": source,
                "strength": "direct",
                "why": "Pinned source contains a loop; no SQL trace or benchmark was run.",
            }
        ],
        "nextCheck": {"method": "runtime", "question": question, "refs": [source]},
    }
    packet = evaluate_packet(ticket, [], parse_assessment(document), RELEASE)
    assert packet.action == "comment_only"
    assert packet.next_check == document["nextCheck"]
    assert packet.to_dict()["nextCheck"] == document["nextCheck"]
    assert question in packet.proposed_comment
    assert source in packet.recommended_step
    assert next_step_kind(packet) == "investigate_runtime"


@pytest.mark.parametrize(
    "change",
    [
        {"method": "close"},
        {"question": "Close this issue now."},
        {"question": "One?\nAnother?"},
        {"refs": ["https://example.test/uncited"]},
    ],
)
def test_malformed_next_question_cannot_override_safe_recommendation(inputs, change):
    ticket = load_export(inputs.input_path)[0]
    check = {
        "method": "artifact",
        "question": "Which release contains this source?",
        "refs": [ticket.key],
    }
    check.update(change)
    packet = evaluate_packet(
        ticket,
        [],
        parse_assessment(
            {
                "key": ticket.key,
                "verdict": "unclear",
                "nextCheck": check,
                "evidence": [
                    {
                        "type": "jira",
                        "ref": ticket.key,
                        "strength": "direct",
                        "why": "Original report only.",
                    }
                ],
            }
        ),
        RELEASE,
    )
    assert not next_step_kind(packet).startswith("investigate_")
    assert "Close this issue now" not in packet.proposed_comment
    assert "https://example.test/uncited" not in packet.proposed_comment


def test_limited_validation_and_question_cannot_salvage_a_definitive_claim(inputs):
    ticket = load_export(inputs.input_path)[0]
    source = "https://example.test/unbound/source.ts"
    unsupported = "The shipped release certainly fails for every installation."
    question = "Which new branch should receive a fix?"
    packet = evaluate_packet(
        ticket,
        [],
        parse_assessment(
            {
                "key": ticket.key,
                "verdict": "still_valid",
                "evidence": [
                    {"type": "code", "ref": source, "strength": "limited", "why": unsupported}
                ],
                "validation": {
                    "method": "code",
                    "release": RELEASE,
                    "result": "persists",
                    "summary": unsupported,
                    "refs": [source],
                },
                "nextCheck": {"method": "artifact", "question": question, "refs": [source]},
            }
        ),
        RELEASE,
    )
    assert packet.verification_errors
    assert packet.verdict == "unclear" and packet.action == "comment_only"
    assert unsupported not in packet.proposed_comment
    assert question not in packet.proposed_comment


def test_search_hits_resolve_actual_merge_state_instead_of_treating_closed_as_unmerged(monkeypatch):
    calls = []

    def gh(args, **kwargs):
        calls.append(args)
        if args[:2] == ["search", "prs"]:
            return json.dumps(
                [
                    {
                        "title": "Fix RHDHBUGS-101",
                        "body": "",
                        "state": "CLOSED",
                        "url": "https://github.com/example/product/pull/1",
                    }
                ]
            )
        assert args[:2] == ["pr", "view"]
        return json.dumps(
            {
                "state": "MERGED",
                "mergedAt": "2026-01-01T00:00:00Z",
                "mergeCommit": {"oid": "a" * 40},
                "baseRefName": "main",
            }
        )

    monkeypatch.setattr(forge, "_run_gh", gh)
    found = forge.search_prs_for_key("RHDHBUGS-101", {}, True, repos=["example/product"])
    assert found[0]["merged"] is True
    assert found[0]["mergeCommit"] == "a" * 40
    assert len(calls) == 2


def test_rate_limit_and_successful_empty_search_are_not_interchangeable(monkeypatch):
    def gh(args, **kwargs):
        if "example/limited" in args:
            raise forge.ForgeAdapterError("HTTP 403 search rate limit")
        return "[]"

    monkeypatch.setattr(forge, "_run_gh", gh)
    log = []
    assert (
        forge.search_prs_for_key(
            "RHDHBUGS-101", {}, True, repos=["example/limited", "example/empty"], search_log=log
        )
        == []
    )
    assert [entry["status"] for entry in log] == ["error", "success"]


def test_invalid_pr_view_is_a_recorded_evidence_error(monkeypatch):
    monkeypatch.setattr(forge, "_run_gh", lambda *args, **kwargs: "[]")
    result = forge.lookup_pr("https://github.com/example/product/pull/1", {}, True)
    assert result["source"] == "error"
    assert result["merged"] is False


def test_export_retries_one_transient_native_read_without_losing_a_ticket(monkeypatch):
    monkeypatch.setattr(
        jira_adapter, "search_acli", lambda *args, **kwargs: [{"key": "RHDHBUGS-1"}]
    )
    calls = []

    def read(issue, field_names):
        calls.append(issue["key"])
        if len(calls) == 1:
            raise jira_adapter.JiraAdapterError("temporary service failure")
        return {"key": "RHDHBUGS-1", "summary": "example", "status": "New", "created": "2025-01-01"}

    monkeypatch.setattr(jira_adapter, "_full_read", read)
    result = jira_adapter.export_from_acli("project = RHDHBUGS")
    assert len(calls) == 2
    assert result["provenance"]["fullReadCount"] == 1


def test_review_queue_links_doc_plans_patches_and_current_holds(inputs):
    import re

    from bugtriage.layout import refresh_review

    key = "RHDHBUGS-101"
    assessment_file = Path(inputs.assessments_dir) / f"{key}.json"
    assessment = json.loads(assessment_file.read_text())
    assessment["handoff"] = {"outcome": "docs", "reason": "Clarify the documented scope."}
    assessment_file.write_text(json.dumps(assessment))
    review = run(inputs).output_dir
    plan = review / "02-fixes/pull-requests" / key / "PLAN.md"
    assert plan.is_file()
    assert not (review / "02-fixes/docs").exists()
    assert "Awaiting follow-through" in (review / "START-HERE.md").read_text()
    for repo in ("chart", "operator"):
        dest = review / "02-fixes/events" / key / repo
        dest.mkdir(parents=True)
        for name in ("PROPOSAL.md", "VERIFY.md", "change.patch", "receipt.json"):
            (dest / name).touch()
        (dest / "proposal.json").write_text(
            json.dumps({"repository": repo, "branch": "main", "kind": "docs"})
        )
    summary = json.loads((review / "run.json").read_text())
    evidence = "01-triage/audit/test.log"
    (review / evidence).write_text("Test passed.")
    summary["cases"] = {
        key: {"stage": "patch", "next": "Review the documented scope.", "evidence": evidence}
    }
    (review / "run.json").write_text(json.dumps(summary))
    legacy = review / "02-fixes/INTAKE.md"
    legacy.write_text("# Bug review\n\nLegacy generated queue.")
    case_page = plan.with_name("CASE.md")
    case_page.write_text("[Review queue](../../INTAKE.md)")
    refresh_review(review)
    assert not legacy.exists()
    assert (case_page.parent / "../../../START-HERE.md").is_file()
    assert "../../../START-HERE.md" in case_page.read_text()
    page = review / "START-HERE.md"
    content = page.read_text()
    queue = content.split("## Other outcomes")[0]
    assert "2 local PR proposals" in queue
    assert "Owner unrecorded — Review the documented scope." in queue
    assert "Documentation patch prepared locally" in queue
    assert "chart main" in queue and "operator main" in queue
    assert key in queue
    for target in re.findall(r"\]\(([^)]+)\)", content):
        assert (page.parent / target).is_file()
    refresh_review(review)
    assert page.read_text() == content


def test_finish_requires_consistent_evidence_for_all_selected_issues(inputs, tmp_path):
    review = run(inputs).output_dir
    packet_file = review / "01-triage/audit/packets.json"
    audit = json.loads(packet_file.read_text())
    key = audit["packets"][0]["key"]
    audit["packets"][0]["customerSignals"] = ["link:Related:RHDHSUPP-22", "text:RHDHSUPP-19"]
    audit["packets"][0]["reporter"] = {
        "displayName": "Fixture Reporter",
        "accountId": "fixture-account",
    }
    packet_file.write_text(json.dumps(audit))
    log = tmp_path / "fixture.log"
    log.write_text("Attempted UI replay; fixture missing identity data.\n")
    row = dict(
        key=key,
        stage="blocked",
        finding="Filter behavior is under investigation.",
        resolution="The local replay is blocked on the missing identity fixture.",
        featureRequest="a new filter option",
        verification="Checked the local reproduction fixture.",
        next="Replay with the missing identity.",
        evidence=log.name,
        blocker="The reporter's identity fixture is unavailable.",
        nextActions=[
            {
                "owner": "Reporter",
                "action": "Supply the missing identity fixture.",
                "links": [{"label": "Fixture log", "path": "@evidence"}],
            }
        ],
    )
    source = tmp_path / "results.json"
    args = ["finish", "--input", str(source), "--out", str(review)]

    def finish(rows):
        source.write_text(json.dumps(rows))
        return cli.main(args)

    initial = (review / "run.json").read_bytes()
    for invalid in (
        [],
        [row, row],
        [{**row, "key": "RHDHBUGS-999"}],
        [{**row, "stage": "patch"}],
        [{**row, "stage": "existing_fix"}],
        [{**row, "stage": "ready_to_close"}],
        [{**row, "evidence": "missing.log"}],
        [{**row, "blocker": ""}],
        [{**row, "resolution": "See https://example.test/unverified"}],
        [{**row, "citationRef": "https://example.test/unverified"}],
        [{**row, "reviewPRs": ["https://github.com/example/fixture/pull/9"]}],
        [
            {
                **row,
                "nextActions": [
                    {**row["nextActions"][0], "links": [{"label": "Log", "path": "../fixture.log"}]}
                ],
            }
        ],
    ):
        assert finish(invalid) == 2
        assert (review / "run.json").read_bytes() == initial
        assert not (review / "01-triage/audit/followthrough").exists()
    assert finish([row]) == 0
    assert (
        "**Reporter** — Supply the missing identity fixture. [Fixture log](01-triage/audit/followthrough/"
        in (review / "START-HERE.md").read_text()
    )
    assert row["resolution"] in (review / "START-HERE.md").read_text()
    assert "Support coordination required" in (review / "START-HERE.md").read_text()
    draft = (review / f"01-triage/comments/{key}.md").read_text()
    assert f"### TL;DR\n\n{row['resolution']} Exact fix version unconfirmed." in draft
    assert "### How this was tested" not in draft
    assert (
        "### Next steps\n\n- **Reporter** — Supply the missing identity fixture: [Fixture log](../../01-triage/audit/followthrough/"
        in draft
    )
    assert (
        draft.splitlines()[-2].rstrip()
        == "rhdh-agentic-bug-triager · AI-generated. Check for accuracy."
    )
    assert draft.splitlines()[-1].startswith("`v1:")
    completed = (review / "run.json").read_bytes()
    case = json.loads(completed)["cases"][key]
    assert "@Fixture Reporter, please open a feature request for a new filter option" in draft
    assert case["supportCases"] == ["RHDHSUPP-22"]
    assert "RHDHSUPP-22" in draft and "RHDHSUPP-19" not in draft
    assert case["featureRequesterMention"]["attrs"] == {
        "id": "fixture-account",
        "text": "@Fixture Reporter",
    }
    assert case["jiraTransition"]["state"] == "no_action" and not case["jiraTransition"]["applied"]
    assert "**Jira handoff.**" in (review / "START-HERE.md").read_text()
    assert case["stage"] == "blocked" and case["blocker"] == row["blocker"]
    assert (review / case["evidence"]).read_bytes() == log.read_bytes()
    assert finish([row]) == 0 and (review / "run.json").read_bytes() == completed

    # A raw fix object's booleans never establish release inclusion on their own.
    packet = audit["packets"][0]
    packet.update(
        fix={
            "pr": "https://github.com/example/fixture/pull/1",
            "merged": True,
            "containedInReviewRelease": True,
        },
        verificationErrors=[],
    )
    packet_file.write_text(json.dumps(audit))
    assert finish([{**row, "stage": "existing_fix"}]) == 2
    packet["fix"]["released"] = True
    packet.update(
        verdict="already_fixed",
        validation={"result": "resolved"},
        evidence=[
            {"type": "pr", "ref": packet["fix"]["pr"], "strength": "direct"},
            {"type": "release_note", "ref": "https://example.test/release", "strength": "direct"},
        ],
        proof={"releaseContains": {"refs": ["https://example.test/release"]}},
    )
    packet_file.write_text(json.dumps(audit))
    assert finish([{**row, "stage": "existing_fix"}]) == 2
    assert (
        finish(
            [
                {
                    **row,
                    "stage": "existing_fix",
                    "next": "Check customer fields before closure.",
                    "releaseNote": {
                        "decision": "internal",
                        "reason": "Only a test fixture changed.",
                    },
                }
            ]
        )
        == 0
    )
    draft = (review / f"01-triage/comments/{key}.md").read_text()
    line = draft.split("### Next steps\n\n")[1].split("\n\n")[0]
    assert (
        line
        == "[PR #1](https://github.com/example/fixture/pull/1) — Check customer fields before closure."
    )
    assert line in (review / "START-HERE.md").read_text()

    note = {"text": "Catalog filters now retain the selected owner.", "type": "Bug Fix"}
    names = ("Release Note Type", "Release Note Text", "Release Note Status")
    packet.update(fixVersions=[], fixVersionsEmpty=True, releaseNoteFields=dict.fromkeys(names))
    packet["fix"]["release"] = "2.1.1"
    packet_file.write_text(json.dumps(audit))
    (tmp_path / "versions.json").write_text(
        json.dumps([{"name": "2.1.1", "archived": False, "released": True}])
    )
    (tmp_path / "edit.json").write_text(
        json.dumps(
            {
                "fields": {
                    "customfield_1": {"name": names[0], "allowedValues": [{"value": "Bug Fix"}]},
                    "customfield_2": {"name": names[2], "allowedValues": [{"value": "Proposed"}]},
                    "customfield_3": {"name": names[1]},
                }
            }
        )
    )
    result = {
        **row,
        "stage": "existing_fix",
        "releaseNote": note,
        "releaseNoteEditMeta": "edit.json",
        "projectVersions": "versions.json",
    }
    assert finish([result]) == 0
    fields = json.loads((review / "run.json").read_text())["cases"][key]["proposedJiraFields"]
    assert fields == {
        names[0]: note["type"],
        names[1]: note["text"],
        names[2]: "Proposed",
        "Fix Version/s": ["2.1.1"],
    }
    for artifact in (review / "START-HERE.md", review / f"01-triage/comments/{key}.md"):
        assert "Release note proposed (Bug Fix): " + note["text"] in artifact.read_text()
    # Without verified Jira choices the text must still reach reviewers.
    pending = {**result, "releaseNote": {"text": note["text"]}}
    del pending["releaseNoteEditMeta"]
    assert finish([pending]) == 0
    completed = (review / "run.json").read_bytes()
    assert finish([pending]) == 0 and (review / "run.json").read_bytes() == completed
    case = json.loads(completed)["cases"][key]
    assert set(case["proposedJiraFields"]) == {"Fix Version/s"}
    for artifact in (review / "START-HERE.md", review / f"01-triage/comments/{key}.md"):
        assert "Release note draft: " + note["text"] in artifact.read_text()
        assert "Jira field review pending" in artifact.read_text()
    retained = {
        **result,
        "releaseNote": {"decision": "retain", "reason": "The workaround still applies."},
    }
    assert finish([retained]) == 2
    packet["releaseNoteFields"].update(
        {
            names[0]: {"value": "Known Issue"},
            names[1]: {"type": "doc", "content": [{"type": "text", "text": "Use YAML view."}]},
            names[2]: {"value": "Done"},
        }
    )
    packet_file.write_text(json.dumps(audit))
    assert finish([retained]) == 0
    for artifact in (review / "START-HERE.md", review / f"01-triage/comments/{key}.md"):
        assert (
            "Existing Known Issue note retained. The workaround still applies."
            in artifact.read_text()
        )
    packet["releaseNoteFields"][names[2]] = {"value": "Approved"}
    packet["fixVersions"] = ["2.0.0"]
    packet_file.write_text(json.dumps(audit))
    assert finish([result]) == 0
    assert not json.loads((review / "run.json").read_text())["cases"][key]["proposedJiraFields"]

    packet.setdefault("investigation", {})["classification"] = {
        "kind": "feature",
        "basis": "Adds a new filter.",
        "ref": key,
    }
    packet_file.write_text(json.dumps(audit))
    assert finish([result]) == 2
    assert finish([{**result, "stage": "classification_review"}]) == 0
    case = json.loads((review / "run.json").read_text())["cases"][key]
    assert not case["proposedJiraFields"]
    assert case["jiraTransition"]["state"] == "no_action"
    assert "Human classification review requested (feature)" in case["proposedComment"]


def test_version_plan_requires_unambiguous_eligible_targets(tmp_path):
    from bugtriage.finish import jira_field_plan

    (tmp_path / "versions.json").write_text(
        json.dumps(
            [
                {"name": "2.2.0", "released": False, "archived": False},
                {"name": "2.1.2", "released": False, "archived": False},
            ]
        )
    )
    packet = {"fixVersionsEmpty": True}
    row = {"projectVersions": "versions.json", "releaseNote": {"text": "Example fix."}}
    target = {
        "repository": "org/repo",
        "branch": "main",
        "releaseTarget": {"version": "2.2.0"},
        "backports": [
            {"decision": "propose", "branch": "release-2.1", "releaseTarget": {"version": "2.1.2"}},
            {"decision": "skip", "branch": "release-2.0"},
        ],
    }

    def fields(proposals):
        return jira_field_plan(packet, "patch", row, proposals, tmp_path)[0]

    assert fields([target]) == {"Fix Version/s": ["2.1.2", "2.2.0"]}
    assert not fields([target, {**target, "releaseTarget": {"version": "2.1.2"}}])
    assert not fields([{**target, "releaseTarget": {}}])
    packet["fixVersionsEmpty"] = False
    assert not fields([target])


@pytest.mark.parametrize("kind", ["feature", "task", "uncertain"])
def test_issue_type_review_overrides_fix_handoff(inputs, kind):
    key = "RHDHBUGS-101"
    path = Path(inputs.assessments_dir) / f"{key}.json"
    document = json.loads(path.read_text())
    document.update(
        investigation={
            "classification": {"kind": kind, "basis": "Scope needs review.", "ref": key}
        },
        handoff={"outcome": "pull-requests"},
    )
    path.write_text(json.dumps(document))
    result = run(inputs)
    packet = result.packets[0]
    assert packet.action == "comment_only"
    assert packet.handoff["outcome"] == "blocked"
    assert "Review issue classification" in packet.proposed_comment
    assert (result.output_dir / "02-fixes" / "blocked" / key / "PLAN.md").is_file()
    document["investigation"]["classification"]["ref"] = "RHDHBUGS-999"
    with pytest.raises(ValueError, match="classification"):
        parse_assessment(document)
