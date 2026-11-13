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
from bugtriage.policy import Assessment, Evidence, evaluate, parse_assessment  # noqa: E402
from bugtriage.report import render_packet  # noqa: E402

NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)


@pytest.fixture
def case():
    ticket = normalize_issue(
        {
            "key": "RHDHBUGS-200",
            "description": "Existing reproduction steps.",
            "comment": {"comments": [], "total": 0},
        }
    )
    assessment = Assessment(
        key=ticket.key,
        disposition="still_valid",
        evidence=[
            Evidence(
                "code",
                "https://example.test/code",
                "The loop still queries once per role.",
                "direct",
            )
        ],
    )
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
    old = replace(packet, current_release="1.9")
    reference = plan_comment(ticket, old, assessment, NOW)["reference"]
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
    assert MARKER_PREFIX in packet.proposed_comment
    assert render_packet(packet, ticket).startswith(packet.proposed_comment)
    # Running a dry run does not become posting history.
    assert ticket.comments == []
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "propose"


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
        evidence=[replace(packet.evidence[0], why="Same observation, rephrased")],
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
    _, packet, assessment = case
    ticket = normalize_issue({"key": packet.key, "comment": history})
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "review_required"


def test_flat_adapter_must_attest_comment_completeness(case):
    _, packet, assessment = case
    ticket = normalize_issue({"key": packet.key, "comments": [], "commentsComplete": True})
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "propose"


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
def test_customer_or_done_tickets_never_propose_comments(case, customer, done):
    ticket, packet, assessment = case
    ticket.customer_signals = ["label:RHDH-Customer"] if customer else []
    ticket.is_done = done
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "suppress"


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
    assert "https://example.test/code" in packet.proposed_comment


def test_default_close_is_a_recommendation_not_a_completed_action(case):
    ticket, _, _ = case
    assessment = Assessment(
        key=ticket.key,
        disposition="no_longer_valid",
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
    packet = evaluate(ticket, [], assessment)
    assert packet.action == "propose_close_obsolete"
    assert "Recommendation: close" in packet.proposed_comment
    assert "Closing as" not in packet.proposed_comment
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "propose"


def test_targeted_next_step_is_used_in_both_report_data_and_default_comment(case):
    ticket, _, _ = case
    assessment = parse_assessment(
        {
            "key": ticket.key,
            "disposition": "unclear",
            "recommendedStep": "Ask Documentation to verify the published title procedure.",
        }
    )
    packet = evaluate(ticket, [], assessment)
    assert packet.recommended_step == assessment.recommended_step
    assert packet.recommended_step in packet.proposed_comment
    assert "reproduction" not in packet.proposed_comment
    assert f"https://redhat.atlassian.net/browse/{ticket.key}" in packet.proposed_comment
