"""All-verdict dry-run decisions and evidence-bounded comment planning."""

import copy
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/jira/rhdh-bug-triage/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bugtriage.comments import attach_comment_plan, plan_comment  # noqa: E402
from bugtriage.duplicates import rank_candidates  # noqa: E402
from bugtriage.model import Comment, normalize_issue  # noqa: E402
from bugtriage.policy import (  # noqa: E402
    CLOSE_ACTIONS,
    PROOF_FIELDS,
    Evidence,
    evaluate,
    input_errors,
    parse_assessment,
    verify_packet,
)

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)
RELEASE = "2.1.0"
SOURCE = "https://example.test/releases/2.1.0/failure.py#L10"
FIXTURES = Path(__file__).parent / "fixtures/bug_triage"
CUSTOMER_FIELDS = {
    "customfield_42": "Customer Name",
    "customfield_99": "Support Case Reference",
}


def ticket(**changes):
    fields = {
        "key": "RHDHBUGS-1",
        "summary": "Filter update drops the typed character",
        "description": "Select a catalog filter, then type in the search input.",
        "status": "Backlog",
        "labels": [],
        "issuelinks": [],
        "fieldNames": CUSTOMER_FIELDS,
        "customfield_42": None,
        "customfield_99": None,
        "comments": [],
        "commentsComplete": True,
    }
    fields.update(changes)
    return normalize_issue(fields)


def assessment(verdict="still_valid", **changes):
    document = {
        "key": "RHDHBUGS-1",
        "verdict": verdict,
        "evidence": [
            {
                "type": "code",
                "ref": SOURCE,
                "why": "The released filter handler clears focus before processing the next key.",
                "strength": "direct",
            }
        ],
        "validation": {
            "release": RELEASE,
            "method": "code",
            "result": "persists",
            "summary": "The current filter handler still clears focus, so the next character is lost.",
            "refs": [SOURCE],
        },
    }
    document.update(changes)
    return parse_assessment(document)


def close_case(kind):
    key = "RHDHBUGS-1010" if kind == "duplicate" else "RHDHBUGS-1006"
    export = json.loads((FIXTURES / "issues.json").read_text())
    # Positive controls model every catalogued field as actually fetched. Let
    # normalization establish coverage rather than setting derived flags.
    for record in export["issues"]:
        record["fieldNames"] = export["fieldNames"]
        fields = record.get("fields", record)
        for field_id in export["fieldNames"]:
            fields.setdefault(field_id, None)
    tickets = [normalize_issue(record) for record in export["issues"]]
    issue = next(item for item in tickets if item.key == key)
    assert issue.customer_fields_complete
    document = json.loads((FIXTURES / "assessments" / f"{key}.json").read_text())
    return issue, rank_candidates(issue, tickets), parse_assessment(document)


@pytest.mark.parametrize(
    "method,kind",
    [("code", "code"), ("runtime", "repro"), ("documentation", "doc"), ("dependency", "doc")],
)
def test_current_release_validation_supports_truthful_still_valid(method, kind):
    issue, finding = ticket(), assessment()
    finding.validation["method"] = method
    finding.evidence[0].type = kind
    packet = evaluate(issue, [], finding, RELEASE)
    assert packet.verdict == "still_valid"
    assert packet.action == "comment_only"
    assert not verify_packet(packet, issue)
    assert finding.evidence[0].why in packet.proposed_comment
    assert f"{method} on release {RELEASE}" in packet.proposed_comment
    assert finding.validation["summary"] in packet.proposed_comment
    if method != "runtime":
        assert "runtime" not in packet.proposed_comment
    assert packet.to_dict()["validation"] == finding.validation
    assert plan_comment(issue, packet, finding, NOW)["status"] == "propose"
    assert "Keep this issue open" in packet.recommended_step
    assert "next y-stream release" in packet.recommended_step
    assert "identify its cause" not in packet.recommended_step


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"release": "1.8.0"},
        {"release": "2.1"},
        {"release": "v2.1.0"},
        {"release": "2.1.0 "},
        {"method": "guess"},
        {"result": "unknown"},
        {"summary": ""},
        {"refs": []},
        {"refs": [SOURCE + "0"]},
    ],
)
def test_one_direct_url_does_not_certify_current_validity(bad):
    finding = assessment()
    finding.validation = {**finding.validation, **bad} if bad else {}
    finding.repro_result, finding.repro_release = "reproduced", "1.8.0"
    packet = evaluate(ticket(), [], finding, RELEASE)
    assert packet.confidence == 0.98  # Citation strength, not factual reliability.
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert packet.proposed_comment
    assert "persists on release" not in packet.proposed_comment
    assert "not a probability" in packet.proposed_comment


def test_status_old_versions_and_no_fix_match_are_not_validity_proof():
    issue = ticket(versions=["1.4.0"], fixVersions=["1.5.0"])
    finding = assessment(validation={}, notes="No PR search matches; issue is open.")
    packet = evaluate(issue, [], finding, RELEASE)
    assert packet.verdict == "unclear"
    assert "unfixed" not in packet.proposed_comment.lower()
    assert "no pr" not in packet.proposed_comment.lower()
    assert "Next, inspect" in packet.recommended_step
    assert "please reproduce" not in packet.proposed_comment.lower()


@pytest.mark.parametrize(
    "finding",
    [
        None,
        parse_assessment({"key": "RHDHBUGS-1"}),
        parse_assessment({"key": "RHDHBUGS-1", "verdict": "still_valid"}),
        parse_assessment({"key": "RHDHBUGS-2", "verdict": "already_fixed"}),
    ],
)
def test_missing_or_mismatched_assessment_is_an_honest_jira_bounded_draft(finding):
    issue = ticket()
    packet = evaluate(issue, [], finding, RELEASE)
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert packet.gaps
    assert "https://redhat.atlassian.net/browse/" + issue.key in packet.proposed_comment
    assert "missing" in packet.recommended_step
    assert "Validation:" not in packet.proposed_comment
    assert packet.proposed_comment.count("Recommended next step:") == 1


@pytest.mark.parametrize("verdict", ["unclear", "needs_repro"])
def test_uncertainty_has_source_summary_and_one_agent_owned_next_step(verdict):
    finding = assessment(
        verdict, validation={}, recommendedStep="Ask Team X to create a PR and backport it."
    )
    issue = ticket(assignee="A Known Assignee", team="Catalog")
    packet = evaluate(issue, [], finding, RELEASE)
    assert packet.action == "comment_only"
    assert packet.verdict == verdict
    assert finding.evidence[0].why in packet.proposed_comment
    assert packet.recommended_step.startswith("Next,")
    assert SOURCE in packet.recommended_step
    assert "I will" not in packet.proposed_comment
    assert "Team X" not in packet.proposed_comment
    assert "backport" not in packet.proposed_comment
    assert "A Known Assignee" in packet.proposed_comment
    assert "Jira team: Catalog" in packet.proposed_comment


def test_unclear_preserves_checked_validation_without_claiming_no_check_occurred():
    finding = assessment("unclear")
    finding.evidence[0].type = "doc"
    finding.validation.update(
        method="documentation",
        result="resolved",
        summary="The current guide resolves the documented path, but the reported environment still needs comparison.",
    )
    packet = evaluate(ticket(), [], finding, RELEASE)
    assert packet.policy_version == 4
    assert packet.verdict == "unclear"
    assert "no definitive triage conclusion is established" in packet.proposed_comment
    assert finding.validation["summary"] in packet.proposed_comment
    assert "no conclusive current-release validation was supplied" not in packet.proposed_comment
    assert "Evidence score: not established" in packet.proposed_comment
    assert "not a probability" in packet.proposed_comment
    assert SOURCE in packet.recommended_step
    assert "I will" not in packet.proposed_comment


def obsolete_assessment():
    finding = assessment("no_longer_valid")
    finding.validation.update(
        result="resolved",
        method="documentation",
        summary="The current configuration schema removed the trigger option.",
    )
    finding.evidence[0].type = "doc"
    finding.proof = {
        "scopeRemoval": {
            "summary": "The current schema no longer accepts the removed option that triggered the failure.",
            "refs": [SOURCE],
        }
    }
    return finding


def test_no_longer_valid_requires_resolved_current_scope_removal_not_closure():
    issue, finding = ticket(), obsolete_assessment()
    packet = evaluate(issue, [], finding, RELEASE)
    assert packet.verdict == "no_longer_valid"
    assert packet.action == "comment_only"
    assert "Why it is gone:" in packet.proposed_comment
    assert "close" not in packet.recommended_step.lower()
    for changed in [replace(finding, proof={}), replace(finding, validation={})]:
        fallback = evaluate(issue, [], changed, RELEASE)
        assert fallback.verdict == "unclear"
        assert fallback.proposed_comment


@pytest.mark.parametrize("kind", ["duplicate", "already_fixed"])
def test_complete_close_controls_keep_advisory_gates_and_full_proof(kind):
    issue, candidates, finding = close_case(kind)
    packet = evaluate(issue, candidates, finding, RELEASE)
    assert packet.action in CLOSE_ACTIONS
    assert not packet.verification_errors
    for name in PROOF_FIELDS[kind]:
        assert finding.proof[name]["summary"] in packet.proposed_comment
    assert "human approval" in packet.proposed_comment
    assert "will close" not in packet.proposed_comment.lower()
    assert "closing" not in packet.proposed_comment.lower()


def test_low_lexical_candidate_with_direct_semantic_proof_can_be_a_duplicate():
    issue, candidates, finding = close_case("duplicate")
    issue.links = []
    candidates = [
        replace(candidate, score=0.12) if candidate.key == finding.duplicate_of else candidate
        for candidate in candidates
    ]
    packet = evaluate(issue, candidates, finding, RELEASE)
    assert not packet.explicit_duplicate_link
    assert packet.confidence >= 0.85
    assert packet.action == "propose_close_duplicate"
    assert not packet.verification_errors


def test_high_lexical_match_and_link_do_not_supply_missing_same_trigger_proof():
    issue, candidates, finding = close_case("duplicate")
    candidates = [replace(candidate, score=0.99) for candidate in candidates]
    finding.evidence[0].why = "Focus is lost only after selecting a catalog filter."
    finding.evidence[1].why = "Navigation, not a filter update, causes focus loss."
    # The source observations do not support an affirmative same-trigger claim.
    finding.proof["sameTrigger"] = None
    packet = evaluate(issue, candidates, finding, RELEASE)
    assert packet.explicit_duplicate_link
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert any("sameTrigger" in error for error in packet.verification_errors)


@pytest.mark.parametrize("kind", ["duplicate", "already_fixed"])
def test_failed_close_gate_becomes_unclear_without_dangerous_old_prose(kind):
    issue, candidates, finding = close_case(kind)
    finding.proof = {}
    finding.recommended_step = "Create a PR and close the unrelated issue."
    finding.evidence[0].why = "DANGEROUS unverified old conclusion."
    packet = evaluate(issue, candidates, finding, RELEASE)
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert packet.verification_errors
    assert packet.proposed_comment
    assert "DANGEROUS" not in packet.proposed_comment
    assert "Create a PR" not in packet.proposed_comment
    assert "Proof:" not in packet.proposed_comment
    assert "Source summary: Supplied" in packet.proposed_comment
    assert "close" not in packet.recommended_step.lower()


@pytest.mark.parametrize("kind", ["already_fixed", "no_longer_valid"])
@pytest.mark.parametrize("repro_result", ["reproduced", "fails", "persists", "arbitrary outcome"])
def test_legacy_current_repro_cannot_be_ignored_for_resolved_findings(kind, repro_result):
    if kind == "already_fixed":
        issue, candidates, finding = close_case(kind)
    else:
        issue, candidates, finding = ticket(), [], obsolete_assessment()
    finding.repro_result, finding.repro_release = repro_result, RELEASE
    packet = evaluate(issue, candidates, finding, RELEASE)
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert any("repro" in error for error in packet.verification_errors)


@pytest.mark.parametrize("alias", ["v2.1.0", "2.1", "2.1.0 "])
@pytest.mark.parametrize(
    "kind,repro_result",
    [
        ("already_fixed", "reproduced"),
        ("already_fixed", "fails"),
        ("already_fixed", "persists"),
        ("no_longer_valid", "reproduced"),
        ("no_longer_valid", "fails"),
        ("no_longer_valid", "persists"),
        ("still_valid", "not_reproduced"),
        ("still_valid", "passes"),
        ("still_valid", "resolved"),
    ],
)
def test_equivalent_current_repro_releases_cannot_bypass_contradictions(alias, kind, repro_result):
    if kind == "already_fixed":
        issue, candidates, finding = close_case(kind)
    else:
        issue, candidates = ticket(), []
        finding = assessment() if kind == "still_valid" else obsolete_assessment()
    finding.repro_result, finding.repro_release = repro_result, alias
    packet = evaluate(issue, candidates, finding, RELEASE)
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert any("contradict" in error for error in packet.verification_errors)
    assert "Evidence score: not established" in packet.proposed_comment
    assert "not a probability" in packet.proposed_comment
    assert "The reported failure is resolved by" not in packet.proposed_comment
    assert "The reported failure persists on release" not in packet.proposed_comment


@pytest.mark.parametrize("repro_release", ["", "not a version"])
def test_unparseable_release_tuples_do_not_manufacture_a_contradiction(repro_release):
    finding = assessment()
    finding.repro_result, finding.repro_release = "not_reproduced", repro_release
    packet = evaluate(ticket(), [], finding, "")
    assert packet.verdict == "unclear"
    assert packet.verification_errors
    assert not any("contradict" in error for error in packet.verification_errors)


@pytest.mark.parametrize("kind", ["already_fixed", "no_longer_valid", "still_valid"])
def test_historical_repro_does_not_override_current_release_evidence(kind):
    if kind == "already_fixed":
        issue, candidates, finding = close_case(kind)
    else:
        issue, candidates = ticket(), []
        finding = assessment() if kind == "still_valid" else obsolete_assessment()
    finding.repro_result = "not_reproduced" if kind == "still_valid" else "reproduced"
    finding.repro_release = "1.8.0"
    packet = evaluate(issue, candidates, finding, RELEASE)
    assert packet.verdict == kind
    assert not packet.verification_errors


def test_current_structured_validation_overrules_old_fixed_claim():
    issue, candidates, finding = close_case("already_fixed")
    finding.validation = {**assessment().validation, "refs": [finding.evidence[0].ref]}
    packet = evaluate(issue, candidates, finding, RELEASE)
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert "The reported failure is resolved" not in packet.proposed_comment


@pytest.mark.parametrize("verdict", ["still_valid", "no_longer_valid"])
def test_current_validation_does_not_override_review_disagreement(verdict):
    finding = assessment() if verdict == "still_valid" else obsolete_assessment()
    finding.independent_passes, finding.agreement = 2, False
    packet = evaluate(ticket(), [], finding, RELEASE)
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert "disagree" in packet.proposed_comment
    assert "persists on release" not in packet.proposed_comment
    assert "Validation:" not in packet.proposed_comment


@pytest.mark.parametrize("kind", ["duplicate", "already_fixed", "still_valid"])
def test_omitted_current_release_never_certifies_a_conclusion(kind):
    if kind in ("duplicate", "already_fixed"):
        issue, candidates, finding = close_case(kind)
    else:
        issue, candidates, finding = ticket(), [], assessment()
    packet = evaluate(issue, candidates, finding)
    assert packet.current_release == ""
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert "authoritative release source" in packet.recommended_step


@pytest.mark.parametrize("status", ["unknown", "None", "N/A", "Unavailable"])
def test_placeholder_status_is_not_known_status(status):
    issue = ticket(status=status)
    packet = evaluate(issue, [], assessment(), RELEASE)
    assert packet.verdict == "unclear"
    assert plan_comment(issue, packet, assessment(), NOW)["status"] == "review_required"


@pytest.mark.parametrize("kind", ["duplicate", "already_fixed"])
def test_customer_receives_a_draft_and_completed_issues_remain_excluded(kind):
    issue, candidates, finding = close_case(kind)
    for changes in ({"customer_signals": ["label:RHDH-Customer"]}, {"is_done": True}):
        excluded = replace(issue, **changes)
        packet = evaluate(excluded, candidates, finding, RELEASE)
        assert packet.action == ("abstain" if excluded.is_done else "comment_only")
        assert bool(packet.proposed_comment) == (not excluded.is_done)


@pytest.mark.parametrize("missing", ["status", "description", "customer"])
def test_incomplete_ticket_does_not_receive_confident_findings_or_post_eligibility(missing):
    issue, candidates, finding = close_case("already_fixed")
    if missing == "customer":
        issue.customer_fields_read = []
    else:
        setattr(issue, missing, "")
    packet = evaluate(issue, candidates, finding, RELEASE)
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert plan_comment(issue, packet, finding, NOW)["status"] == "review_required"
    assert packet.proposed_comment


@pytest.mark.parametrize("kind", ["duplicate", "already_fixed"])
def test_missing_mapped_customer_field_blocks_close_advice_and_delivery(kind):
    issue, candidates, finding = close_case(kind)
    assert not input_errors(issue)
    assert evaluate(issue, candidates, finding, RELEASE).action in CLOSE_ACTIONS
    raw = copy.deepcopy(issue.raw)
    del raw["fields"]["customfield_10749"]  # Known mapped Support Case Reference.
    partial = normalize_issue(raw)
    assert partial.customer_fields_read
    assert not partial.unmapped_custom_fields
    assert not partial.customer_fields_complete
    assert not partial.customer_signals
    assert any("customfield_10749" in gap for gap in partial.read_gaps)
    assert any("customer-field" in error for error in input_errors(partial))
    packet = evaluate(partial, candidates, finding, RELEASE)
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert any("customer-field" in error for error in packet.verification_errors)
    assert plan_comment(partial, packet, finding, NOW)["status"] == "review_required"
    assert packet.proposed_comment
    assert "The reported failure is resolved by" not in packet.proposed_comment


@pytest.mark.parametrize("kind", ["still_valid", "no_longer_valid"])
def test_private_validity_draft_survives_unknown_customer_context_but_delivery_is_blocked(kind):
    raw = copy.deepcopy(ticket().raw)
    del raw["customfield_99"]
    issue = normalize_issue(raw)
    finding = assessment() if kind == "still_valid" else obsolete_assessment()
    assert not issue.customer_fields_complete
    assert issue.customer_fields_read == ["Customer Name"]
    assert input_errors(issue)
    assert not input_errors(issue, require_customer_coverage=False)
    packet = evaluate(issue, [], finding, RELEASE)
    assert packet.verdict == kind
    assert packet.action == "comment_only"
    assert not packet.verification_errors
    assert not verify_packet(packet, issue)
    assert finding.validation["summary"] in packet.proposed_comment
    assert f"on release {RELEASE}" in packet.proposed_comment
    attach_comment_plan(issue, packet, finding, NOW, 14)
    assert packet.comment_plan["status"] == "review_required"
    assert packet.proposed_comment


def test_known_customer_receives_a_draft_even_when_private_behavior_is_supported():
    raw = copy.deepcopy(ticket().raw)
    del raw["customfield_99"]
    raw["customfield_42"] = "Example Customer"
    issue = normalize_issue(raw)
    assert not issue.customer_fields_complete
    assert issue.customer_signals
    packet = evaluate(issue, [], assessment(), RELEASE)
    assert packet.action == "comment_only"
    assert packet.proposed_comment


def test_minimal_complete_comments_do_not_prove_status_or_customer_coverage():
    issue = normalize_issue({"key": "RHDHBUGS-1006", "comments": [], "commentsComplete": True})
    _, _, finding = close_case("already_fixed")
    packet = evaluate(issue, [], finding, RELEASE)
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert plan_comment(issue, packet, finding, NOW)["status"] == "review_required"


def add_comment(issue, comment_id="10", body="Unrelated release planning.", days=20):
    issue.comments.append(
        Comment(id=comment_id, body=body, created=(NOW - timedelta(days=days)).isoformat())
    )


def history_review(issue, finding, **changes):
    finding.history_review = {
        "complete": True,
        "checkedCommentIds": [item.id for item in issue.comments],
        "equivalentAdvice": False,
        "pendingAction": False,
        "summary": "Read each fetched comment; discussion concerns unrelated release planning.",
        "refs": [
            f"https://redhat.atlassian.net/browse/{issue.key}?focusedCommentId={item.id}"
            for item in issue.comments
        ],
        **changes,
    }


def test_unrelated_unmarked_discussion_can_be_autonomously_reviewed():
    issue, finding = ticket(), assessment()
    add_comment(issue)
    packet = evaluate(issue, [], finding, RELEASE)
    assert plan_comment(issue, packet, finding, NOW)["status"] == "review_required"
    history_review(issue, finding)
    assert plan_comment(issue, packet, finding, NOW)["status"] == "propose"


def test_history_review_is_parsed_from_assessment_input():
    issue, finding = ticket(), assessment()
    add_comment(issue)
    history_review(issue, finding)
    parsed = parse_assessment({"key": issue.key, "historyReview": finding.history_review})
    assert parsed.history_review == finding.history_review


@pytest.mark.parametrize(
    "change",
    [
        {"complete": False},
        {"checkedCommentIds": []},
        {"checkedCommentIds": ["other"]},
        {"summary": ""},
        {"pendingAction": "false"},
        {"refs": []},
        {"refs": ["https://example.test/comment/10"]},
        {"refs": ["https://redhat.atlassian.net/browse/RHDHBUGS-2?focusedCommentId=10"]},
    ],
)
def test_history_review_requires_exact_ids_strict_flags_and_source_comment_links(change):
    issue, finding = ticket(), assessment()
    add_comment(issue)
    history_review(issue, finding, **change)
    packet = evaluate(issue, [], finding, RELEASE)
    assert plan_comment(issue, packet, finding, NOW)["status"] == "review_required"


@pytest.mark.parametrize("flag", ["equivalentAdvice", "pendingAction"])
def test_reviewed_equivalent_or_pending_advice_stays_suppressed(flag):
    issue, finding = ticket(), assessment()
    add_comment(issue, days=365)
    history_review(issue, finding, **{flag: True})
    packet = evaluate(issue, [], finding, RELEASE)
    assert plan_comment(issue, packet, finding, NOW)["status"] == "suppress"


def test_history_review_does_not_cover_a_later_unreviewed_comment():
    issue, finding = ticket(), assessment()
    add_comment(issue)
    history_review(issue, finding)
    add_comment(issue, "11")
    packet = evaluate(issue, [], finding, RELEASE)
    assert plan_comment(issue, packet, finding, NOW)["status"] == "review_required"


def test_fingerprint_ignores_prose_order_and_incidental_evidence_urls():
    issue, finding = ticket(), assessment()
    packet = evaluate(issue, [], finding, RELEASE)
    reference = plan_comment(issue, packet, finding, NOW)["reference"]
    finding.evidence[0].why = "A rephrased summary of the same code."
    finding.validation["summary"] = "The same result, rephrased."
    finding.evidence.append(
        Evidence("doc", "https://example.test/additional", "Additional background.", "supporting")
    )
    finding.evidence.reverse()
    finding.recommended_step = "Please notify everybody."
    changed = evaluate(issue, [], finding, RELEASE)
    assert plan_comment(issue, changed, finding, NOW)["reference"] == reference
    add_comment(issue, body=reference)
    assert plan_comment(issue, changed, finding, NOW)["status"] == "suppress"


@pytest.mark.parametrize(
    "field,value", [("method", "runtime"), ("result", "unknown"), ("release", "2.2.0")]
)
def test_validation_semantics_change_the_fingerprint(field, value):
    issue, finding = ticket(), assessment()
    packet = evaluate(issue, [], finding, RELEASE)
    original = plan_comment(issue, packet, finding, NOW)["reference"]
    changed = copy.deepcopy(packet)
    changed.validation[field] = value
    assert plan_comment(issue, changed, finding, NOW)["reference"] != original


def test_exact_repeat_is_suppressed_even_with_malformed_time_and_incomplete_history():
    issue, finding = ticket(), assessment()
    packet = evaluate(issue, [], finding, RELEASE)
    marker = plan_comment(issue, packet, finding, NOW)["reference"]
    issue.comments = [Comment(body=marker, created="invalid")]
    issue.comments_complete = False
    assert plan_comment(issue, packet, finding, NOW)["status"] == "suppress"


@pytest.mark.parametrize("complete", [False, True])
def test_draft_visibility_is_independent_of_history_eligibility_and_footer_is_once(complete):
    issue, finding = ticket(), assessment("unclear", validation={})
    issue.comments_complete = complete
    packet = evaluate(issue, [], finding, RELEASE)
    attach_comment_plan(issue, packet, finding, NOW, 14)
    assert packet.comment_plan["status"] == ("propose" if complete else "review_required")
    first = packet.proposed_comment
    attach_comment_plan(issue, packet, finding, NOW, 14)
    assert packet.proposed_comment == first
    assert packet.to_dict()["proposedComment"]
    assert first.count("rhdh-agentic-bug-triager · AI-generated. Check for accuracy.") == 1


def test_changed_advice_requires_cooldown_and_cited_completion_even_with_history_review():
    issue, finding = ticket(), assessment()
    prior = evaluate(issue, [], assessment("unclear", validation={}), RELEASE)
    marker = plan_comment(issue, prior, finding, NOW)["reference"]
    add_comment(issue, body=marker, days=14)
    add_comment(issue, "11")
    history_review(issue, finding)
    packet = evaluate(issue, [], finding, RELEASE)
    assert plan_comment(issue, packet, finding, NOW)["status"] == "suppress"
    finding.follow_up = {
        "priorCommentId": "10",
        "state": "completed",
        "evidence": [
            {
                "type": "comment",
                "ref": f"https://redhat.atlassian.net/browse/{issue.key}?focusedCommentId=11",
                "why": "The requested inspection was completed.",
                "strength": "direct",
            }
        ],
    }
    assert plan_comment(issue, packet, finding, NOW)["status"] == "propose"
    issue.comments[0].created = (NOW - timedelta(days=13)).isoformat()
    assert plan_comment(issue, packet, finding, NOW)["status"] == "suppress"


def test_later_collection_gaps_do_not_rewrite_the_verified_draft():
    issue, finding = ticket(), assessment("unclear", validation={})
    packet = evaluate(issue, [], finding, RELEASE)
    packet.gaps.append("affects version absent from the export")
    assert plan_comment(issue, packet, finding, NOW)["status"] == "propose"
