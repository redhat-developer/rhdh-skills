"""Discovery routes are independent leads, never additional closure authority."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/jira/rhdh-bug-triage/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bugtriage.discovery import discover, query_plan  # noqa: E402
from bugtriage.duplicates import rank_candidates, score_candidate  # noqa: E402
from bugtriage.jira import JiraAdapterError  # noqa: E402
from bugtriage.model import normalize_issue  # noqa: E402
from bugtriage.policy import evaluate, parse_assessment, verify_packet  # noqa: E402
from bugtriage.run import RunConfig, run  # noqa: E402


def record(key="RHDHBUGS-2", **fields):
    return {
        "key": key,
        "fields": {
            "summary": "Template Editor returns 404 for non-super user",
            "description": "Open Template Editor as test2. Expected empty templates, got 404.",
            "status": {"name": "New", "statusCategory": {"name": "To Do"}},
            "created": "2026-10-01T04:44:03Z",
            "labels": [],
            "issuelinks": [],
            "comments": [],
            "commentsComplete": True,
            **fields,
        },
    }


def ticket(key="RHDHBUGS-2", **fields):
    return normalize_issue(record(key, **fields))


def link(key, direction="outward", kind="Duplicate"):
    return {"type": {"name": kind}, direction + "Issue": {"key": key}}


def leads(result):
    return {lead["key"]: lead for lead in result["leads"]}


def test_routes_remain_independent_and_closed_copy_carries_comment_evidence():
    seed = ticket(issuelinks=[link("RHDHBUGS-1")])
    copy = ticket(
        "RHDHBUGS-1",
        created="2026-10-01T04:43:52Z",
        status={"name": "Closed", "statusCategory": {"name": "Done"}},
        fixVersions=[{"name": "2.1.0"}],
        comments=[
            {
                "id": "5",
                "body": "Should be fixed in https://github.com/o/r/pull/7. However still failing.",
            }
        ],
    )
    result = discover(seed, [seed, copy])
    assert set(leads(result)[copy.key]["foundBy"]) == {
        "link_graph",
        "burst",
        "closed_corpus",
        "comments",
        "fix_first",
    }
    assert {"fix_claim", "uncertain_claim", "negative_or_followup"} <= set(
        result["commentSignals"][0]["kinds"]
    )
    assert not any(query["outcome"] != "not_run" for query in result["queries"])


def test_burst_alone_does_not_merge_unrelated_report():
    seed = ticket()
    other = ticket(
        "RHDHBUGS-3",
        summary="Git repository export archives fail",
        description="Cannot create an archive",
    )
    assert "burst" not in leads(discover(seed, [other])).get(other.key, {}).get("foundBy", [])


def test_weak_lexical_candidate_does_not_expand_its_comment_graph():
    seed = ticket()
    other = ticket("RHDHBUGS-3", comments=[{"id": "1", "body": "Unrelated followup RHIDP-999"}])
    result = discover(seed, [other])
    assert other.key in leads(result)
    assert "RHIDP-999" not in leads(result)


def test_missing_linked_record_and_reverse_direction_remain_visible():
    seed = ticket(issuelinks=[link("RHDHBUGS-999"), link("RHDHBUGS-3")])
    other = ticket("RHDHBUGS-3", issuelinks=[link(seed.key)])
    result = discover(seed, [other])
    assert leads(result)["RHDHBUGS-999"]["available"] is False
    assert any("points back" in warning for warning in leads(result)[other.key]["warnings"])


def test_aliases_from_history_are_not_duplicate_candidates_and_search_separately():
    raw = record()
    raw["changelog"] = {
        "histories": [
            {"items": [{"field": "Key", "fromString": "RHIDP-55", "toString": "RHDHBUGS-2"}]}
        ]
    }
    seed = normalize_issue(raw)
    alias = ticket("RHIDP-55")
    assert seed.former_keys == ["RHIDP-55"]
    assert rank_candidates(seed, [alias]) == []
    assert score_candidate(seed, alias).same_record
    assert alias.key not in leads(discover(seed, [alias]))
    queries = query_plan(seed)
    assert {q["term"] for q in queries if q["kind"] == "key"} == {seed.key, alias.key}
    assert all(" OR " not in q["jql"] for q in queries)


def test_queries_do_not_use_generic_error_tokens_or_bare_http_status():
    seed = ticket(
        description="Additional information: the application failed each time with 403. Config key `auth.provider` fails."
    )
    terms = {q["term"] for q in query_plan(seed)}
    assert not {"additional", "application", "each", "403", "failed"} & terms
    assert "auth.provider" in terms


def test_shared_verified_alias_identity_is_not_ranked_as_another_report():
    seed = ticket(formerKeys=["RHIDP-55"])
    other = ticket("RHDHBUGS-3", formerKeys=["RHIDP-55"])
    assert not rank_candidates(seed, [other])
    assert other.key not in leads(discover(seed, [other]))


def test_live_failures_empty_capped_and_unrun_are_distinct(monkeypatch):
    calls = []

    def search(jql, limit):
        calls.append(jql)
        if len(calls) == 1:
            raise JiraAdapterError("permission denied")
        if len(calls) == 2:
            return []
        return [{"key": "RHIDP-7"}]

    monkeypatch.setattr("bugtriage.discovery.search_acli", search)
    monkeypatch.setattr("bugtriage.discovery.hydrate_acli", lambda hit, names: record(hit["key"]))
    seed = ticket(
        formerKeys=["RHIDP-1", "RHIDP-2"], description="Config key `auth.provider` fails."
    )
    result = discover(seed, [], live=True, max_queries=3, query_limit=1)
    outcomes = [q["outcome"] for q in result["queries"]]
    assert outcomes[:3] == ["failed", "empty", "capped"]
    assert "not_run" in outcomes
    assert result["candidateRecords"][0]["key"] == "RHIDP-7"
    assert leads(result)["RHIDP-7"]["foundBy"] == ["defect_search"]


def test_hydration_budget_and_read_failures_do_not_hide_hits(monkeypatch):
    monkeypatch.setattr("bugtriage.discovery.search_acli", lambda *a, **kw: [{"key": "RHIDP-7"}])
    result = discover(ticket(), [], live=True, max_queries=1, hydrate_limit=0)
    assert leads(result)["RHIDP-7"]["available"] is False
    assert any("budget exhausted" in gap for gap in result["gaps"])

    def failed(*a):
        raise JiraAdapterError("full read denied")

    monkeypatch.setattr("bugtriage.discovery.hydrate_acli", failed)
    result = discover(ticket(), [], live=True, max_queries=1)
    assert any("full read failed" in gap for gap in result["gaps"])
    assert result["queries"][0]["outcome"] == "returned"


def test_failed_hydrations_consume_the_read_budget(monkeypatch):
    monkeypatch.setattr(
        "bugtriage.discovery.search_acli",
        lambda *a, **kw: [{"key": f"RHIDP-{i}"} for i in range(10, 15)],
    )
    calls = []

    def failed(hit, names):
        calls.append(hit["key"])
        raise JiraAdapterError("denied")

    monkeypatch.setattr("bugtriage.discovery.hydrate_acli", failed)
    result = discover(ticket(), [], live=True, max_queries=2, hydrate_limit=2)
    assert len(calls) == 2
    assert len(leads(result)) == 5


@pytest.mark.parametrize("state", ["partial_fix_supported", "verified_for_stated_scope"])
def test_incomplete_verification_cannot_become_positive_fix_state(state):
    assessment = parse_assessment(
        {
            "key": "RHDHBUGS-2",
            "disposition": "unclear",
            "evidence": [
                {
                    "type": "jira",
                    "ref": "RHDHBUGS-2",
                    "why": "A merged candidate exists but no working subset is demonstrated",
                    "strength": "direct",
                }
            ],
            "fixEvidence": {"state": state, "scenario": "Default visibility", "covered": []},
        }
    )
    packet = evaluate(ticket(), [], assessment, "2.1.0")
    assert packet.fix_evidence["state"] == "not_established"
    assert any("positive" in error for error in packet.verification_errors)
    assert packet.action == "comment_only"


def test_positive_subset_is_preserved_without_full_fix_or_closure():
    assessment = parse_assessment(
        {
            "key": "RHDHBUGS-2",
            "disposition": "unclear",
            "evidence": [
                {
                    "type": "repro",
                    "ref": "https://example.com/test/1",
                    "why": "Opt-in workaround tested with labeled resources",
                    "strength": "direct",
                }
            ],
            "fixEvidence": {
                "state": "partial_fix_supported",
                "scenario": "OOM",
                "covered": [
                    {
                        "summary": "Labeled-resource path works in the cited test",
                        "refs": ["https://example.com/test/1"],
                    }
                ],
                "unverified": ["Default unlabeled cluster behavior"],
            },
        }
    )
    packet = evaluate(ticket(), [], assessment, "2.1.0")
    assert packet.fix_evidence["state"] == "partial_fix_supported"
    assert packet.disposition == "unclear"
    assert packet.action == "comment_only"


def test_assessed_fix_is_not_encoded_as_unassessed():
    assessment = parse_assessment(
        {
            "key": "RHDHBUGS-2",
            "disposition": "unclear",
            "fixEvidence": {
                "state": "not_assessed",
                "validation": {"summary": "Examined but missing proof"},
            },
        }
    )
    packet = evaluate(ticket(), [], assessment, "2.1.0")
    assert packet.fix_evidence["state"] == "not_established"


def test_same_record_cannot_pass_duplicate_gate_even_if_explicitly_supplied():
    seed = ticket(formerKeys=["RHIDP-1"])
    packet = evaluate(
        seed,
        [score_candidate(seed, ticket("RHIDP-1"))],
        parse_assessment({"key": seed.key, "disposition": "duplicate", "duplicateOf": "RHIDP-1"}),
        "2.1.0",
    )
    assert any("same record" in error for error in packet.verification_errors)
    assert packet.action == "comment_only"
    assert verify_packet(packet, seed) == []


def test_duplicate_report_identity_is_preserved_without_canonical_closure():
    seed, other = ticket(), ticket("RHDHBUGS-1")
    assessment = parse_assessment(
        {
            "key": seed.key,
            "disposition": "unclear",
            "evidence": [
                {
                    "type": "jira",
                    "ref": key,
                    "why": "Compared the exact trigger and expected correction",
                    "strength": "direct",
                }
                for key in [seed.key, other.key]
            ],
            "comparisons": [
                {
                    "key": other.key,
                    "relationship": "duplicate_supported",
                    "summary": "Same reported test2 Template Editor 404 and required empty state",
                    "refs": [seed.key, other.key],
                }
            ],
        }
    )
    packet = evaluate(seed, [score_candidate(seed, other)], assessment, "2.1.0")
    assert packet.comparisons[0]["relationship"] == "duplicate_supported"
    assert packet.disposition == "unclear"
    assert packet.action == "comment_only"
    assert not packet.independent_passes


def test_positive_comparison_without_both_sources_is_rejected():
    seed = ticket()
    assessment = parse_assessment(
        {
            "key": seed.key,
            "disposition": "unclear",
            "comparisons": [
                {
                    "key": "RHDHBUGS-1",
                    "relationship": "duplicate_supported",
                    "summary": "Unproven match",
                    "refs": [seed.key],
                }
            ],
        }
    )
    packet = evaluate(seed, [], assessment, "2.1.0")
    assert packet.comparisons[0]["relationship"] == "insufficient_evidence"
    assert packet.comparisons[0]["rejectedRelationship"] == "duplicate_supported"
    assert any("both reports" in error for error in packet.verification_errors)


def test_fix_only_self_comparison_is_not_a_duplicate_recommendation():
    seed = ticket()
    assessment = parse_assessment(
        {
            "key": seed.key,
            "disposition": "unclear",
            "comparisons": [
                {
                    "key": seed.key,
                    "relationship": "same_record",
                    "summary": "Fix-only assessment of the same tracker",
                }
            ],
        }
    )
    packet = evaluate(seed, [], assessment, "2.1.0")
    assert packet.to_dict()["sameRecord"] is True
    assert packet.action == "comment_only"


def test_public_pipeline_includes_nonlexical_linked_candidate_and_does_not_invent_verdict(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"issues": [record()]}))
    corpus = tmp_path / "corpus.json"
    corpus.write_text(
        json.dumps(
            {
                "issues": [
                    record(
                        "RHDHBUGS-1",
                        summary="Entirely different wording",
                        description="No shared words",
                        issuelinks=[link("RHDHBUGS-2")],
                    )
                ]
            }
        )
    )
    assessments = tmp_path / "assessments"
    assessments.mkdir()
    (assessments / "RHDHBUGS-2.json").write_text(
        json.dumps(
            {
                "key": "RHDHBUGS-2",
                "disposition": "unclear",
                "notes": "Report compared, ownership and cause remain unknown",
            }
        )
    )
    result = run(
        RunConfig(
            input_path=str(source),
            output_dir=str(tmp_path / "run"),
            assessments_dir=str(assessments),
            corpus_path=str(corpus),
            scope="all-open",
            all_tickets=True,
            current_release="2.1.0",
            release_evidence="https://example.com/release/2.1.0",
            as_of="2026-11-18",
        )
    )
    packet = result.packets[0]
    assert "link_graph" in leads(packet.discovery)["RHDHBUGS-1"]["foundBy"]
    assert "RHDHBUGS-1" in {candidate.key for candidate in packet.duplicate_candidates}
    assert packet.disposition == "unclear"
    assert result.manifest["writes"] == []
