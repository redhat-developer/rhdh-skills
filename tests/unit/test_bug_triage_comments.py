"""Comment fidelity and repeat-suppression contracts; no network or writes."""

import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/jira/rhdh-bug-triage/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bugtriage.comments import MARKER_PREFIX, attach_comment_plan, plan_comment  # noqa: E402
from bugtriage.model import Comment, normalize_issue  # noqa: E402
from bugtriage.policy import (  # noqa: E402
    Assessment,
    Evidence,
    evaluate,
    load_assessment,
    parse_assessment,
)

NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)


@pytest.fixture
def case():
    ticket = normalize_issue(
        {
            "key": "RHDHBUGS-1006",
            "summary": "External S3 endpoint lookup fails",
            "description": "Existing reproduction steps.",
            "status": {"name": "Backlog", "statusCategory": {"name": "To Do"}},
            "fieldNames": {
                "customfield_10746": "Customer Name",
                "customfield_10716": "Customers",
                "customfield_10747": "Customer Impact",
                "customfield_10748": "Case Link",
                "customfield_10749": "Support Case Reference",
            },
            "customfield_10746": None,
            "customfield_10716": None,
            "customfield_10747": None,
            "customfield_10748": None,
            "customfield_10749": None,
            "labels": [],
            "issuelinks": [],
            "comment": {"comments": [], "total": 0},
        }
    )
    assessment = load_assessment(
        str(Path(__file__).parent / "fixtures/bug_triage/assessments/RHDHBUGS-1006.json")
    )
    assert ticket.customer_fields_complete is True
    assert ticket.unmapped_custom_fields == []
    return ticket, evaluate(ticket, [], assessment, "2.1.0"), assessment


def previous(ticket, reference, days=20, comment_id="10"):
    ticket.comments.append(
        Comment(
            id=comment_id,
            body="Triage reference: `" + reference + "`.",
            created=(NOW - timedelta(days=days)).isoformat(),
        )
    )


def changed_history(case, days=20):
    ticket, packet, assessment = case
    old_assessment = Assessment(key=ticket.key, verdict="unclear")
    old = evaluate(ticket, [], old_assessment, "2.1.0")
    reference = plan_comment(ticket, old, old_assessment, NOW)["reference"]
    previous(ticket, reference, days)
    return ticket, packet, assessment


def follow_up(assessment, strength="direct", comment_id="10", state="completed"):
    assessment.follow_up = {
        "priorCommentId": comment_id,
        "state": state,
        "evidence": [
            {
                "type": "comment",
                "ref": "https://example.test/result",
                "why": "The owner supplied the requested retest.",
                "strength": strength,
            }
        ],
    }


def test_first_comment_is_only_a_local_proposal(case):
    ticket, packet, assessment = case
    attach_comment_plan(ticket, packet, assessment, NOW, 14)
    assert packet.comment_plan["status"] == "propose"
    assert packet.proposed_comment.endswith(
        f"`v1:{packet.comment_plan['reference'].split(':')[-1]}`"
    )
    # Running a dry run does not become posting history.
    assert ticket.comments == []
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "propose"


@pytest.mark.parametrize("attributed", [False, True])
def test_short_reference_requires_triager_attribution(case, attributed):
    ticket, packet, assessment = case
    attach_comment_plan(ticket, packet, assessment, NOW, 14)
    draft = packet.proposed_comment
    body = draft if attributed else draft.splitlines()[-1]
    ticket.comments.append(Comment(id="12", body=body, created=NOW.isoformat()))
    plan = plan_comment(ticket, packet, assessment, NOW)
    assert (plan["reason"] == "The same recommendation is already on Jira.") is attributed


def test_identical_recommendation_stays_suppressed_even_after_completion(case):
    ticket, packet, assessment = case
    previous(ticket, plan_comment(ticket, packet, assessment, NOW)["reference"], days=365)
    follow_up(assessment)
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "suppress"


def test_fingerprint_ignores_prose_changes_and_evidence_order(case):
    ticket, packet, assessment = case
    first = plan_comment(ticket, packet, assessment, NOW)["reference"]
    changed = replace(
        packet,
        recommended_step="A rephrased request",
        evidence=[
            replace(item, why="Same observation, rephrased") for item in reversed(packet.evidence)
        ],
    )
    assert plan_comment(ticket, changed, assessment, NOW)["reference"] == first


def test_changed_recommendation_must_wait_for_cooldown(case):
    ticket, packet, assessment = changed_history(case, days=3)
    follow_up(assessment)
    plan = plan_comment(ticket, packet, assessment, NOW)
    assert plan["status"] == "suppress"
    assert plan["earliestReconsiderAt"] == (NOW + timedelta(days=11)).isoformat()


@pytest.mark.parametrize("state", ["pending", "unknown", "completed", "superseded"])
def test_time_or_a_claim_without_direct_evidence_does_not_clear_pending_work(case, state):
    ticket, packet, assessment = changed_history(case)
    follow_up(assessment, strength="supporting", state=state)
    ticket.comments.append(
        Comment(id="reply", created=NOW.isoformat(), body="Still looking at it.")
    )
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "suppress"


@pytest.mark.parametrize("state", ["completed", "superseded"])
def test_changed_recommendation_with_verified_followup_after_cooldown(case, state):
    ticket, packet, assessment = changed_history(case, days=14)
    follow_up(assessment, state=state)
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "propose"


def test_followup_must_name_latest_posted_triage_comment(case):
    ticket, packet, assessment = changed_history(case)
    follow_up(assessment, comment_id="unrelated")
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "suppress"


def test_malformed_followup_evidence_fails_closed(case):
    ticket, packet, assessment = changed_history(case)
    follow_up(assessment)
    assessment.follow_up["evidence"].append(None)
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "suppress"


@pytest.mark.parametrize(
    "history", [None, {"comments": [], "total": 3}, [], {"comments": [], "total": 0, "startAt": 3}]
)
def test_incomplete_history_requires_review(case, history):
    original, packet, assessment = case
    ticket = normalize_issue({**original.raw, "comment": history})
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "review_required"


def test_flat_adapter_must_attest_comment_completeness(case):
    original, packet, assessment = case
    payload = {**original.raw, "comments": [], "commentsComplete": True}
    payload.pop("comment")
    ticket = normalize_issue(payload)
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "propose"


def test_unfetched_mapped_support_field_blocks_fixed_advice_and_delivery(case):
    original, _, assessment = case
    payload = dict(original.raw)
    payload.pop("customfield_10749")
    ticket = normalize_issue(payload)
    assert ticket.customer_fields_complete is False
    assert ticket.customer_signals == []
    packet = evaluate(ticket, [], assessment, "2.1.0")
    assert packet.verdict == "unclear"
    assert packet.action == "comment_only"
    assert "Verdict: unclear" in packet.proposed_comment
    assert "close " not in packet.recommended_step.lower()
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "review_required"


@pytest.mark.parametrize(
    "created,comment_id,body",
    [
        ("invalid", "10", MARKER_PREFIX + "a" * 64),
        ((NOW + timedelta(days=1)).isoformat(), "10", MARKER_PREFIX + "a" * 64),
        (NOW.isoformat(), "", MARKER_PREFIX + "a" * 64),
        (NOW.isoformat(), "10", "rhdh-bug-triage:v2:unknown"),
    ],
)
def test_unreliable_history_requires_review(case, created, comment_id, body):
    ticket, packet, assessment = case
    ticket.comments.append(Comment(id=comment_id, created=created, body=body))
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "review_required"


def test_zero_cooldown_does_not_bypass_pending_action(case):
    ticket, packet, assessment = changed_history(case, days=1)
    assert plan_comment(ticket, packet, assessment, NOW, 0)["status"] == "suppress"


def test_negative_cooldown_is_rejected(case):
    with pytest.raises(ValueError):
        plan_comment(*case, NOW, -1)


@pytest.mark.parametrize("customer,done", [(True, False), (False, True)])
def test_only_done_tickets_suppress_supported_comments(case, customer, done):
    ticket, packet, assessment = case
    ticket.customer_signals = ["label:RHDH-Customer"] if customer else []
    ticket.is_done = done
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == (
        "suppress" if done else "propose"
    )


@pytest.mark.parametrize(
    "body",
    [
        "Closing as fixed.",
        "Recommendation: close as fixed.",
        "Recommendation: keep open. Based on https://example.test/code.",
        "Recommendation: keep open. See [unverified](https://unrelated.test/source).",
        "Keep open. See [source](https://example.test/code) and https://example.test/result.",
        "RHDHBUGS-200: see [source](https://example.test/code). Keep open.",
    ],
)
def test_unsafe_or_unlinked_comment_requires_review(case, body):
    ticket, packet, assessment = case
    packet.proposed_comment = body
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "review_required"


def test_source_inspection_does_not_claim_a_runtime_reproduction(case):
    _, packet, _ = case
    assert "reproducible" not in packet.proposed_comment.lower()
    assert "https://github.com/redhat-developer/rhdh/pull/999" in packet.proposed_comment


def test_obsolete_claim_without_current_release_scope_validation_is_unclear(case):
    ticket, _, _ = case
    assessment = Assessment(
        key=ticket.key,
        verdict="no_longer_valid",
        evidence=[
            Evidence(
                "doc",
                "https://example.test/removal",
                "The configuration option was removed.",
                "direct",
            )
        ],
        independent_passes=2,
        agreement=True,
    )
    packet = evaluate(ticket, [], assessment, "2.1.0")
    assert packet.action == "comment_only"
    assert packet.verdict == "unclear"
    assert "Verdict: unclear" in packet.proposed_comment
    assert "close " not in packet.recommended_step.lower()
    assert "\nProof:" not in packet.proposed_comment
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "propose"


def test_unclear_draft_cannot_turn_legacy_advice_into_a_human_reproduction_request(case):
    ticket, _, _ = case
    assessment = parse_assessment(
        {
            "key": ticket.key,
            "verdict": "unclear",
            "recommendedStep": "Ask Documentation to verify the published title procedure.",
        }
    )
    packet = evaluate(ticket, [], assessment, "2.1.0")
    assert packet.action == "comment_only"
    assert packet.verdict == "unclear"
    assert "Verdict: unclear" in packet.proposed_comment
    assert packet.recommended_step
    assert "Ask Documentation" not in packet.recommended_step
    assert "Ask Documentation" not in packet.proposed_comment
    assert "reproduce" not in packet.recommended_step.lower()
    assert "close " not in packet.recommended_step.lower()
