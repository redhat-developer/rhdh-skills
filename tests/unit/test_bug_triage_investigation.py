"""General bug diagnosis is distinct from closure and posting eligibility."""

import copy
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/jira/rhdh-bug-triage/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bugtriage.model import Ticket  # noqa: E402
from bugtriage.policy import (  # noqa: E402
    Evidence,
    evaluate,
    investigation_errors,
    investigation_outcome,
    parse_assessment,
)

SOURCE = "https://github.com/example/product/blob/abc123/handler.ts"
EVIDENCE = [Evidence("code", SOURCE, "An awaited loop serializes requests.", "direct")]


def record(result="violated"):
    return {
        "status": "completed",
        "release": "2.1.0",
        "scope": "The explicit sequencing mechanism in the inspected release source.",
        "mechanism": "The handler awaits each independent request before starting the next.",
        "requirements": [
            {
                "statement": "Independent requests are processed concurrently.",
                "result": result,
                "observed": "Each loop iteration awaits the prior operation.",
                "method": "code",
                "refs": [SOURCE],
            }
        ],
    }


@pytest.mark.parametrize("result", ["satisfied", "violated"])
def test_completed_investigation_requires_method_matching_direct_observations(result):
    assert investigation_errors(record(result), EVIDENCE, "2.1.0") == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "not_started"),
        ("status", "anything"),
        ("release", "1.10.0"),
        ("scope", ""),
        ("mechanism", []),
        ("requirements", []),
        ("requirements", "claims"),
        ("requirements", [None]),
    ],
)
def test_incomplete_or_malformed_investigation_is_rejected(field, value):
    data = record()
    data[field] = value
    assert investigation_errors(data, EVIDENCE, "2.1.0")


@pytest.mark.parametrize(
    "field,value",
    [
        ("statement", ""),
        ("observed", None),
        ("result", "fixed"),
        ("method", "report"),
        ("method", {}),
        ("refs", ["RHDHBUGS-1"]),
        ("refs", [None]),
        ("refs", []),
    ],
)
def test_invalid_requirement_cannot_masquerade_as_verification(field, value):
    data = record()
    data["requirements"][0][field] = value
    assert investigation_errors(data, EVIDENCE, "2.1.0")


def test_report_and_supporting_source_cannot_establish_current_behavior():
    for evidence in (
        [Evidence("jira", SOURCE, "Report is open.", "direct")],
        [Evidence("code", SOURCE, "Unverified lead.", "supporting")],
    ):
        assert investigation_errors(record(), evidence, "2.1.0")


def test_unknown_check_is_blocked_not_completed_and_names_its_missing_check():
    data = record("unknown")
    assert investigation_errors(data, EVIDENCE, "2.1.0")
    data["status"] = "blocked"
    assert investigation_errors(data, EVIDENCE, "2.1.0")
    data["blocker"] = "Inspect an existing trace with two simultaneous imports."
    assert investigation_errors(data, EVIDENCE, "2.1.0") == []
    data["requirements"][0]["result"] = "violated"
    assert investigation_errors(data, EVIDENCE, "2.1.0")


def packet(data, verdict="unclear", **extra):
    assessment = parse_assessment(
        {
            "key": "RHDHBUGS-1",
            "verdict": verdict,
            "evidence": [e.to_dict() for e in EVIDENCE],
            "investigation": data,
            **extra,
        }
    )
    return evaluate(
        Ticket(key="RHDHBUGS-1", summary="Sequential request handling"), [], assessment, "2.1.0"
    )


def test_scoped_diagnosis_survives_unrelated_closure_gate_failure():
    result = packet(record(), verdict="already_fixed")
    assert result.verdict == "unclear"
    assert result.action == "comment_only"
    assert result.verification_errors
    assert investigation_outcome(result) == "requirement_violated"
    assert result.to_dict()["investigationOutcome"] == "requirement_violated"
    assert record()["requirements"][0]["observed"] in result.proposed_comment
    assert "whole-fix recommendation contradicts" in "; ".join(result.verification_errors)


def test_malformed_investigation_does_not_leak_as_accepted_comment():
    data = record()
    data["requirements"][0]["refs"] = []
    result = packet(data)
    assert investigation_outcome(result) == "invalid"
    assert data["mechanism"] not in result.proposed_comment
    assert result.verification_errors


def test_unknown_requirement_does_not_conceal_a_positive_counterexample():
    data = record()
    unknown = copy.deepcopy(data["requirements"][0])
    unknown.update(result="unknown", statement="Runtime latency meets the expected bound.")
    data["requirements"].append(unknown)
    data.update(status="blocked", blocker="No measured latency trace for the original workload.")
    result = packet(data)
    assert result.verification_errors == []
    assert investigation_outcome(result) == "requirement_violated"
    assert data["blocker"] in result.proposed_comment


def test_scoped_success_is_not_automatic_closure_or_runtime_verification():
    result = packet(record("satisfied"))
    assert result.verdict == "unclear"
    assert result.action == "comment_only"
    assert investigation_outcome(result) == "requirements_satisfied_in_stated_scope"
    assert result.validation == {}


def test_held_resolution_points_at_customer_coverage():
    from bugtriage.policy import _next_step, next_step_kind

    result = packet(record("satisfied"))
    result.verification_errors = [
        "customer-field read coverage is incomplete; retrieve mapped fields, labels and links"
    ]
    assert next_step_kind(result) == "verify_customer_coverage"
    assert "field map" in _next_step(result)
