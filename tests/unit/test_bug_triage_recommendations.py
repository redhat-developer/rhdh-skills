"""Fail-closed recommendation contracts, including positive controls. No network."""

import copy
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills/jira/rhdh-bug-triage"
sys.path.insert(0, str(SKILL / "scripts"))

from bugtriage import cli  # noqa: E402
from bugtriage.comments import attach_comment_plan, plan_comment  # noqa: E402
from bugtriage.duplicates import rank_candidates, score_candidate  # noqa: E402
from bugtriage.evaluate import evaluate as score_run  # noqa: E402
from bugtriage.forge import ForgeAdapterError, collect_for_ticket, search_prs_for_key  # noqa: E402
from bugtriage.model import Comment, load_export, normalize_issue  # noqa: E402
from bugtriage.policy import evaluate as evaluate_finding  # noqa: E402
from bugtriage.policy import parse_assessment, verify_packet  # noqa: E402
from bugtriage.run import RunConfig, RunError, run  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures/bug_triage"
NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)
CURRENT_RELEASE = "2.1.0"
RELEASE_EVIDENCE = (
    "https://docs.redhat.com/en/documentation/red_hat_developer_hub/2.1/html/release_notes/"
)


def evaluate(ticket, candidates, assessment):
    return evaluate_finding(ticket, candidates, assessment, current_release=CURRENT_RELEASE)


def comment_text(output, key):
    text = (output / "01-triage" / "comments" / f"{key}.md").read_text(encoding="utf-8")
    return text.strip()


def assert_unclear_draft(packet):
    assert packet.action == "comment_only"
    assert packet.verdict == "unclear"
    if packet.comment_plan:
        assert "unclear" in packet.proposed_comment
        assert packet.recommended_step in packet.proposed_comment
        assert packet.proposed_comment.strip()
    else:
        assert "Verdict: unclear" in packet.proposed_comment
        assert "Recommended next step:" in packet.proposed_comment
    assert packet.recommended_step
    assert "close " not in packet.recommended_step.lower()
    assert "\nProof:" not in packet.proposed_comment
    assert "The reported failure is resolved by" not in packet.proposed_comment
    assert "This issue duplicates" not in packet.proposed_comment


def case(kind):
    key = "RHDHBUGS-1010" if kind == "duplicate" else "RHDHBUGS-1006"
    tickets = load_export(str(FIXTURES / "issues.json"))
    ticket = next(t for t in tickets if t.key == key)
    assert ticket.customer_fields_complete is True
    document = json.loads((FIXTURES / "assessments" / f"{key}.json").read_text())
    return ticket, rank_candidates(ticket, tickets), document


@pytest.mark.parametrize("kind", ["duplicate", "already_fixed"])
def test_positive_controls_have_agreed_shape_and_ignore_legacy_mutation_receipts(kind):
    ticket, candidates, document = case(kind)
    document["comment"] = "Closing another issue now."
    document["recommendedStep"] = "Close some unrelated issue instead."
    packet = evaluate(ticket, candidates, parse_assessment(document))
    assert packet.action in {"propose_close_duplicate", "propose_close_fixed"}
    assert not packet.verification_errors
    assert packet.proposed_comment.startswith("Re: [" + ticket.key + "]")
    assert "Recommended next step:" in packet.proposed_comment
    assert "Proof:" in packet.proposed_comment
    assert "Evidence score:" in packet.proposed_comment
    assert "Closing another" not in packet.proposed_comment
    assert "unrelated issue" not in packet.proposed_comment


@pytest.mark.parametrize("verdict", ["still_valid", "no_longer_valid", "unclear", ""])
def test_validity_claims_without_current_release_validation_produce_unclear_drafts(verdict):
    ticket, candidates, document = case("already_fixed")
    document["verdict"] = verdict
    packet = evaluate(ticket, candidates, parse_assessment(document))
    attach_comment_plan(ticket, packet, parse_assessment(document), NOW, 14)
    assert_unclear_draft(packet)
    assert packet.comment_plan["status"] == "propose"
    if verdict in ("still_valid", "no_longer_valid", ""):
        assert packet.gaps


def test_legacy_needs_repro_without_evidence_is_unclear_not_a_human_reproduction_ping():
    ticket, candidates, document = case("already_fixed")
    document["verdict"] = "needs_repro"
    document["evidence"] = []
    packet = evaluate(ticket, candidates, parse_assessment(document))
    assert_unclear_draft(packet)
    assert "reproduce" not in packet.recommended_step.lower()
    assert "ask " not in packet.recommended_step.lower()


CLAIMS = [
    (kind, claim)
    for kind, claims in {
        "duplicate": ["sameFailure", "sameTrigger", "sameFix", "canonical"],
        "already_fixed": ["fixMatches", "releaseContains", "validation"],
    }.items()
    for claim in claims
]


@pytest.mark.parametrize("kind,claim", CLAIMS)
@pytest.mark.parametrize(
    "bad",
    [
        None,
        {"summary": "", "refs": []},
        {"summary": "Trust me", "refs": ["https://uncited.test/fix"]},
    ],
)
def test_each_missing_or_uncited_proof_claim_downgrades_close_advice_to_unclear(kind, claim, bad):
    ticket, candidates, document = case(kind)
    document["proof"][claim] = bad
    packet = evaluate(ticket, candidates, parse_assessment(document))
    assert_unclear_draft(packet)
    assert any("proof." + claim in gap for gap in packet.gaps)


@pytest.mark.parametrize(
    "field", ["merged", "released", "coversWholeIssue", "containedInReviewRelease"]
)
@pytest.mark.parametrize("value", [False, "false", "true", 1, None])
def test_truthy_or_missing_fix_attestations_never_authorize_closure(field, value):
    ticket, candidates, document = case("already_fixed")
    document["fix"][field] = value
    packet = evaluate(ticket, candidates, parse_assessment(document))
    assert_unclear_draft(packet)


@pytest.mark.parametrize(
    "field,value",
    [
        ("release", "unknown"),
        ("release", "2.1.0-rc1"),
        ("release", "2.1.0 garbage"),
        ("release", "2.2.0"),
        ("reviewRelease", "1.9.10"),
        ("reviewRelease", ""),
        ("pr", "https://github.com/other/repo/pull/1"),
        ("commit", "bare-sha"),
    ],
)
def test_release_and_named_artifact_must_match_verified_scope(field, value):
    ticket, candidates, document = case("already_fixed")
    document["fix"][field] = value
    assert_unclear_draft(evaluate(ticket, candidates, parse_assessment(document)))


@pytest.mark.parametrize("kind", ["duplicate", "already_fixed"])
@pytest.mark.parametrize(
    "review",
    [
        {"independentPasses": 1, "agree": True},
        {"independentPasses": 2, "agree": False},
        {"independentPasses": "2", "agree": "true"},
    ],
)
def test_independent_review_cannot_be_invented_by_truthy_values(kind, review):
    ticket, candidates, document = case(kind)
    document["review"] = review
    assert_unclear_draft(evaluate(ticket, candidates, parse_assessment(document)))


@pytest.mark.parametrize(
    "target_date", ["", "invalid", "2023-07-01T09:00:00Z", "2026-01-01T00:00:00Z"]
)
def test_outward_duplicate_link_never_overrides_unknown_or_newer_chronology(target_date):
    ticket, candidates, document = case("duplicate")
    candidates = [
        replace(c, created=target_date) if c.key == document["duplicateOf"] else c
        for c in candidates
    ]
    packet = evaluate(ticket, candidates, parse_assessment(document))
    assert packet.explicit_duplicate_link
    assert_unclear_draft(packet)


@pytest.mark.parametrize(
    "changes",
    [
        {"customer_signals": ["label:RHDH-Customer"]},
        {"duplicate_of": ["RHDHBUGS-1"]},
        {"resolution": "Duplicate"},
    ],
)
def test_canonical_target_is_not_a_customer_or_another_duplicate(changes):
    ticket, candidates, document = case("duplicate")
    candidates = [
        replace(c, **changes) if c.key == document["duplicateOf"] else c for c in candidates
    ]
    assert_unclear_draft(evaluate(ticket, candidates, parse_assessment(document)))


def test_outward_link_does_not_replace_retrieving_the_canonical_report():
    ticket, _, document = case("duplicate")
    assert_unclear_draft(evaluate(ticket, [], parse_assessment(document)))


@pytest.mark.parametrize("claim", ["sameFailure", "sameTrigger"])
def test_similarity_claim_must_cite_both_reports(claim):
    ticket, candidates, document = case("duplicate")
    document["proof"][claim]["refs"] = [document["duplicateOf"]]
    assert_unclear_draft(evaluate(ticket, candidates, parse_assessment(document)))


@pytest.mark.parametrize("kind", ["duplicate", "already_fixed"])
@pytest.mark.parametrize("confidence", [0.79, float("nan"), float("inf"), 1.0])
def test_independent_verifier_rejects_tampered_confidence(kind, confidence):
    ticket, candidates, document = case(kind)
    packet = evaluate(ticket, candidates, parse_assessment(document))
    packet.confidence = confidence
    assert verify_packet(packet, ticket)
    assert plan_comment(ticket, packet, parse_assessment(document), NOW)["status"] == "suppress"


def test_verifier_rechecks_saved_merge_release_and_proof_not_just_direct_citation():
    ticket, candidates, document = case("already_fixed")
    packet = evaluate(ticket, candidates, parse_assessment(document))
    for field, value in [
        ("merged", False),
        ("released", False),
        ("coversWholeIssue", False),
        ("release", "3.0.0"),
        ("containedInReviewRelease", False),
    ]:
        tampered = copy.deepcopy(packet)
        tampered.fix[field] = value
        assert verify_packet(tampered, ticket)
    packet.proof = {}
    assert verify_packet(packet, ticket)


def test_direct_canonical_citations_accept_jira_urls_as_well_as_keys():
    ticket, candidates, document = case("duplicate")
    replacements = {
        e["ref"]: "https://redhat.atlassian.net/browse/" + e["ref"] for e in document["evidence"]
    }
    for item in document["evidence"]:
        item["ref"] = replacements[item["ref"]]
    for claim in document["proof"].values():
        claim["refs"] = [replacements[ref] for ref in claim["refs"]]
    assert (
        evaluate(ticket, candidates, parse_assessment(document)).action == "propose_close_duplicate"
    )


def test_unmarked_owner_hold_requires_human_review_not_an_automatic_first_comment():
    ticket, candidates, document = case("already_fixed")
    ticket.comments_complete = True
    ticket.comments = [
        Comment(
            id="owner-hold",
            body="Put this on hold until migration is resolved.",
            created=NOW.isoformat(),
        )
    ]
    assessment = parse_assessment(document)
    packet = evaluate(ticket, candidates, assessment)
    assert plan_comment(ticket, packet, assessment, NOW)["status"] == "review_required"


def test_adf_hidden_links_feed_search_and_customer_exclusion():
    ticket = normalize_issue(
        {
            "key": "RHDHBUGS-1",
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "inlineCard",
                        "attrs": {"url": "https://redhat.atlassian.net/browse/RHIDP-12903"},
                    },
                    {
                        "type": "text",
                        "text": "support",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {
                                    "href": "https://redhat.atlassian.net/browse/ACCOUNT-123"
                                },
                            }
                        ],
                    },
                ],
            },
        }
    )
    assert "RHIDP-12903" in collect_for_ticket(ticket, {}, False)["linkedJiraKeys"]
    assert "text:ACCOUNT-123" in ticket.customer_signals


@pytest.mark.parametrize(
    "name,value",
    [
        ("customer name", "Customer"),
        ("SFDC Cases Links", "https://example.test/case"),
        ("Customer Cloud Subscription (CCS)", "subscription"),
    ],
)
def test_flat_customer_fields_remain_close_disabled(name, value):
    ticket = normalize_issue({"key": "RHDHBUGS-1", name: value})
    assert ticket.customer_signals


def test_zero_sfdc_count_does_not_manufacture_a_customer_link():
    ticket = normalize_issue({"key": "RHDHBUGS-1", "SFDC Cases Counter": 0})
    assert ticket.customer_signals == []


def test_rate_limited_search_is_recorded_not_silently_reported_as_zero_matches(monkeypatch):
    def fail(*args, **kwargs):
        raise ForgeAdapterError("HTTP 403: API rate limit exceeded")

    monkeypatch.setattr("bugtriage.forge._run_gh", fail)
    log = []
    assert search_prs_for_key("RHDHBUGS-1", {}, True, repos=["x/y"], search_log=log) == []
    assert log[0]["status"] == "error"
    assert "403" in log[0]["error"]


def test_search_does_not_confuse_numeric_prefixes_with_exact_issue_keys():
    cache = {"x": {"title": "RHDHBUGS-12345 fix"}}
    assert not search_prs_for_key("RHDHBUGS-1234", cache, False)
    assert search_prs_for_key("RHDHBUGS-12345", cache, False)


def test_explicit_unclear_assessments_produce_drafts_without_human_investigation_requests(tmp_path):
    output = tmp_path / "run"
    assessments = tmp_path / "assessments"
    assessments.mkdir()
    for ticket in load_export(str(FIXTURES / "issues.json")):
        (assessments / f"{ticket.key}.json").write_text(
            json.dumps({"key": ticket.key, "verdict": "unclear", "evidence": []})
        )
    result = run(
        RunConfig(
            input_path=str(FIXTURES / "issues.json"),
            output_dir=str(output),
            current_release=CURRENT_RELEASE,
            release_evidence=RELEASE_EVIDENCE,
            assessments_dir=str(assessments),
            size=5,
            as_of="2026-11-09",
        )
    )
    for packet in result.packets:
        assert_unclear_draft(packet)
        assert "ask " not in packet.recommended_step.lower()
        assert "reproduce" not in packet.recommended_step.lower()
    comments = list((output / "01-triage" / "comments").glob("*.md"))
    assert len(comments) == 5
    assert {path.stem for path in comments} == {p.key for p in result.packets}
    assert result.manifest["counts"]["abstained"] == 0
    assert result.manifest["counts"]["surfacedRecommendations"] == 5
    assert result.manifest["counts"]["closeProposals"] == 0
    assert result.manifest["writes"] == []


def test_occupied_output_is_refused_without_overwriting_user_or_old_proposals(tmp_path):
    output = tmp_path / "run"
    output.mkdir()
    sentinel = output / "my-review.md"
    sentinel.write_text("Do not change this")
    with pytest.raises(RunError, match="already exists"):
        run(
            RunConfig(
                input_path=str(FIXTURES / "issues.json"),
                output_dir=str(output),
                current_release=CURRENT_RELEASE,
                release_evidence=RELEASE_EVIDENCE,
            )
        )
    assert sentinel.read_text() == "Do not change this"
    assert list(output.iterdir()) == [sentinel]


def test_strict_evaluation_allows_honest_uncertainty_without_counting_a_fixed_prediction(tmp_path):
    ticket, candidates, document = case("already_fixed")
    document["fix"]["merged"] = False
    packet = evaluate(ticket, candidates, parse_assessment(document))
    assert_unclear_draft(packet)
    truth = {packet.key: {"verdict": "already_fixed"}}
    result = score_run([packet], truth)
    assert result.abstained == 1
    assert result.predicted["already_fixed"] == 0
    assert result.recall["already_fixed"] == 0
    packets = tmp_path / "packets.json"
    labels = tmp_path / "truth.json"
    packets.write_text(json.dumps({"packets": [packet.to_dict()]}))
    labels.write_text(json.dumps(truth))
    assert (
        cli.main(["evaluate", "--packets", str(packets), "--truth", str(labels), "--strict"]) == 0
    )


def test_wrong_canonical_target_is_a_false_close_not_a_precision_success():
    ticket, candidates, document = case("duplicate")
    packet = evaluate(ticket, candidates, parse_assessment(document))
    result = score_run(
        [packet], {packet.key: {"verdict": "duplicate", "duplicateOf": "RHDHBUGS-9999"}}
    )
    assert len(result.false_closes) == 1
    assert result.precision["duplicate"] == 0


def test_surfaced_payload_is_exactly_the_same_in_all_three_artifacts(tmp_path):
    sample = tmp_path / "sample.json"
    sample.write_text(
        json.dumps(
            {
                "schemaVersion": 3,
                "currentRelease": CURRENT_RELEASE,
                "scope": "aged",
                "eligibleCount": 10,
                "tickets": [
                    {"key": key, "kind": "control"} for key in ["RHDHBUGS-1006", "RHDHBUGS-1010"]
                ],
            }
        )
    )
    output = tmp_path / "run"
    result = run(
        RunConfig(
            input_path=str(FIXTURES / "issues.json"),
            output_dir=str(output),
            current_release=CURRENT_RELEASE,
            release_evidence=RELEASE_EVIDENCE,
            sample_path=str(sample),
            assessments_dir=str(FIXTURES / "assessments"),
            as_of="2026-11-09",
        )
    )
    assert len(list((output / "01-triage" / "comments").glob("*.md"))) == len(result.packets)
    for packet in result.packets:
        assert comment_text(output, packet.key) == packet.proposed_comment
        assert (
            packet.proposed_comment.count(
                "rhdh-agentic-bug-triager · AI-generated. Check for accuracy."
            )
            == 1
        )


def test_already_posted_recommendation_has_no_new_handoff_file(tmp_path):
    ticket, candidates, document = case("already_fixed")
    assessment = parse_assessment(document)
    packet = evaluate(ticket, candidates, assessment)
    reference = plan_comment(ticket, packet, assessment, NOW)["reference"]
    export = json.loads((FIXTURES / "issues.json").read_text())
    issue = next(row for row in export["issues"] if row["key"] == ticket.key)
    issue["fields"]["comment"] = {
        "total": 1,
        "comments": [
            {
                "id": "posted-1",
                "created": "2025-01-01T00:00:00Z",
                "body": "Triage reference: " + reference,
            }
        ],
    }
    export_path = tmp_path / "input.json"
    export_path.write_text(json.dumps({"fieldNames": export["fieldNames"], "issues": [issue]}))
    output = tmp_path / "run"
    result = run(
        RunConfig(
            input_path=str(export_path),
            output_dir=str(output),
            current_release=CURRENT_RELEASE,
            release_evidence=RELEASE_EVIDENCE,
            size=1,
            assessments_dir=str(FIXTURES / "assessments"),
            as_of="2026-11-14",
        )
    )
    assert result.packets[0].comment_plan["status"] == "suppress"
    assert not (output / "01-triage" / "proposed").exists()
    comment = (output / "01-triage" / "comments" / f"{ticket.key}.md").read_text()
    assert comment.strip() == result.packets[0].proposed_comment
    assert comment.rstrip().endswith(f"`{reference.removeprefix('rhdh-bug-triage:')}`")
    assert result.manifest["counts"]["surfacedRecommendations"] == 1


@pytest.mark.parametrize("kind", ["duplicate", "already_fixed"])
def test_completed_and_customer_tickets_cannot_pass_even_with_complete_proof(kind):
    ticket, candidates, document = case(kind)
    assessment = parse_assessment(document)
    done = copy.deepcopy(ticket)
    done.is_done = True
    customer = copy.deepcopy(ticket)
    customer.customer_signals = ["label:RHDH-Customer"]
    for blocked in [done, customer]:
        packet = evaluate(blocked, candidates, assessment)
        assert packet.action == ("abstain" if blocked.is_done else "comment_only")
        assert bool(packet.proposed_comment) == (not blocked.is_done)


def test_high_lexical_duplicate_still_requires_complete_semantic_proof_without_a_link():
    ticket, _, document = case("duplicate")
    canonical = next(
        t for t in load_export(str(FIXTURES / "issues.json")) if t.key == document["duplicateOf"]
    )
    ticket.summary, ticket.description, ticket.links = canonical.summary, canonical.description, []
    candidates = [score_candidate(ticket, canonical)]
    assert candidates[0].score >= 0.85
    assert (
        evaluate(ticket, candidates, parse_assessment(document)).action == "propose_close_duplicate"
    )
    document.pop("proof")
    assert_unclear_draft(evaluate(ticket, candidates, parse_assessment(document)))


@pytest.mark.parametrize(
    "claim,ref",
    [
        ("releaseContains", "https://github.com/redhat-developer/rhdh/pull/999"),
        ("validation", "https://github.com/redhat-developer/rhdh/releases/tag/v2.1.0"),
        ("fixMatches", "https://github.com/redhat-developer/rhdh/releases/tag/v2.1.0"),
    ],
)
def test_fixed_proof_claims_need_the_correct_artifact_types(claim, ref):
    ticket, candidates, document = case("already_fixed")
    document["proof"][claim]["refs"] = [ref]
    assert_unclear_draft(evaluate(ticket, candidates, parse_assessment(document)))


def test_replanning_does_not_duplicate_the_reference_footer():
    ticket, candidates, document = case("already_fixed")
    assessment = parse_assessment(document)
    packet = evaluate(ticket, candidates, assessment)
    attach_comment_plan(ticket, packet, assessment, NOW, 14)
    first = packet.proposed_comment
    attach_comment_plan(ticket, packet, assessment, NOW, 14)
    assert packet.proposed_comment == first
    assert (
        packet.proposed_comment.count(
            "rhdh-agentic-bug-triager · AI-generated. Check for accuracy."
        )
        == 1
    )


def test_duplicate_chain_cannot_retain_and_close_the_same_canonical_tracker(tmp_path):
    _, _, template = case("duplicate")
    field_names = json.loads((FIXTURES / "issues.json").read_text())["fieldNames"]
    customer_fields = {field_id: None for field_id, name in field_names.items() if name != "Team"}
    issues = [
        dict(
            key=key,
            summary="Search input loses focus after filter update",
            description="Selecting a catalog filter drops the next keystroke.",
            created=created,
            status="Backlog",
            versions=["1.9.0"],
            labels=[],
            issuelinks=[],
            fieldNames=field_names,
            **customer_fields,
            comments=[],
            commentsComplete=True,
        )
        for key, created in [
            ("RHDHBUGS-300", "2023-08-01T00:00:00Z"),
            ("RHDHBUGS-200", "2023-06-01T00:00:00Z"),
            ("RHDHBUGS-100", "2023-01-01T00:00:00Z"),
        ]
    ]
    export = tmp_path / "issues.json"
    export.write_text(json.dumps(issues))
    assessments = tmp_path / "assessments"
    assessments.mkdir()
    (assessments / "RHDHBUGS-100.json").write_text(
        json.dumps({"key": "RHDHBUGS-100", "verdict": "unclear", "evidence": []})
    )
    for source, target in [("RHDHBUGS-300", "RHDHBUGS-200"), ("RHDHBUGS-200", "RHDHBUGS-100")]:
        encoded = (
            json.dumps(template).replace("RHDHBUGS-1010", source).replace("RHDHBUGS-1009", target)
        )
        (assessments / (source + ".json")).write_text(encoded)
    output = tmp_path / "run"
    result = run(
        RunConfig(
            input_path=str(export),
            output_dir=str(output),
            current_release=CURRENT_RELEASE,
            release_evidence=RELEASE_EVIDENCE,
            assessments_dir=str(assessments),
            size=3,
            as_of="2026-11-14",
        )
    )
    packets = {p.key: p for p in result.packets}
    assert packets["RHDHBUGS-200"].action == "propose_close_duplicate"
    assert_unclear_draft(packets["RHDHBUGS-300"])
    comments = output / "01-triage" / "comments"
    assert (comments / "RHDHBUGS-300.md").is_file()
    assert (comments / "RHDHBUGS-200.md").is_file()
