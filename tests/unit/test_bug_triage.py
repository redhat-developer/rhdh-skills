"""Behavior tests for the read-only RHDH aged-bug triage skill."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = PROJECT_ROOT / "skills" / "jira" / "rhdh-bug-triage"
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bug_triage"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bugtriage import cli  # noqa: E402
from bugtriage.collect import CollectConfig, collect  # noqa: E402
from bugtriage.duplicates import (  # noqa: E402
    DUPLICATE_CLOSE_THRESHOLD,
    distinctive_phrases,
    rank_candidates,
    score_candidate,
)
from bugtriage.evaluate import evaluate, load_truth, render_evaluation  # noqa: E402
from bugtriage.forge import load_cache, lookup_pr, normalize_pr  # noqa: E402
from bugtriage.jira import JiraAdapterError, parse_acli_json, search_acli  # noqa: E402
from bugtriage.model import (  # noqa: E402
    Link,
    Ticket,
    age_days,
    load_export,
    normalize_issue,
    parse_datetime,
)
from bugtriage.policy import (  # noqa: E402
    Assessment,
    Evidence,
    Packet,
    load_assessment,
    verify_packet,
)
from bugtriage.policy import evaluate as evaluate_packet  # noqa: E402
from bugtriage.report import (  # noqa: E402
    render_manifest,
    render_packet,
    render_report,
    render_summary_csv,
)
from bugtriage.run import (  # noqa: E402
    RunConfig,
    RunError,
    build_sample_manifest,
    run,
)
from bugtriage.selection import Control, SelectionConfig, select_sample  # noqa: E402

AS_OF = datetime(2026, 11, 9, tzinfo=timezone.utc)


def fixture_tickets():
    return load_export(str(FIXTURES / "issues.json"))


def by_key():
    return {ticket.key: ticket for ticket in fixture_tickets()}


def sample_manifest(tmp_path: Path, size: int = 5) -> Path:
    tickets = fixture_tickets()
    config = SelectionConfig(
        size=size,
        aged_days=90,
        seed=18094,
        controls=[
            Control(key="RHDHBUGS-1009", label="still-valid"),
            Control(key="RHDHBUGS-1010", label="duplicate"),
        ],
    )
    manifest = build_sample_manifest(tickets, config, AS_OF, "project = RHDHBUGS")
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


class TestNormalization:
    def test_rest_and_flat_shapes_normalize(self):
        tickets = by_key()
        assert len(tickets) == 12
        assert tickets["RHDHBUGS-1002"].description.startswith("Same failure")
        assert tickets["RHDHBUGS-1011"].team == "RHDH Plugins"
        assert tickets["RHDHBUGS-1011"].components == ["Build"]

    def test_customer_signals_cover_label_link_and_field(self):
        tickets = by_key()
        assert "label:RHDH-Customer" in tickets["RHDHBUGS-1003"].customer_signals
        assert any(
            signal.startswith("link:Related:RHDHSUPP-456")
            for signal in tickets["RHDHBUGS-1004"].customer_signals
        )
        assert "field:Customer Name" in tickets["RHDHBUGS-1005"].customer_signals
        assert tickets["RHDHBUGS-1001"].customer_signals == []

    def test_done_and_pr_extraction(self):
        tickets = by_key()
        assert tickets["RHDHBUGS-1012"].is_done
        assert not tickets["RHDHBUGS-1001"].is_done
        assert tickets["RHDHBUGS-1006"].pr_urls == [
            "https://github.com/redhat-developer/rhdh/pull/999"
        ]

    def test_duplicate_link_parsed_with_direction(self):
        links = by_key()["RHDHBUGS-1010"].links
        assert any(link.type == "Duplicate" and link.key == "RHDHBUGS-1009" for link in links)

    def test_flat_mcp_shape_with_comments_and_underscore_links(self):
        ticket = normalize_issue(
            {
                "key": "RHDHBUGS-9001",
                "summary": "Flat record",
                "status": {"name": "Backlog", "category": "To Do"},
                "issue_type": {"name": "Bug"},
                "customfield_10001": {"value": {"name": "RHDH Install"}},
                "comments": [
                    {
                        "author": {"display_name": "Reviewer"},
                        "body": "Still reproducible on 2.1.0.",
                        "created": "2026-01-01T00:00:00.000+0000",
                    }
                ],
                "issuelinks": [
                    {
                        "type": {"name": "Duplicate"},
                        "outward_issue": {
                            "key": "RHDHBUGS-9000",
                            "fields": {"summary": "Original", "status": {"name": "New"}},
                        },
                    }
                ],
            }
        )
        assert ticket.team == "RHDH Install"
        assert ticket.comments[0].author == "Reviewer"
        assert ticket.links[0].key == "RHDHBUGS-9000"
        assert ticket.links[0].type == "Duplicate"

    def test_jira_plus_offset_parses(self):
        parsed = parse_datetime("2023-12-01T10:00:00.000+0000")
        assert parsed is not None
        assert parsed.year == 2023

    def test_age_days_is_deterministic_with_as_of(self):
        assert age_days("2023-12-01T10:00:00.000+0000", AS_OF) == 1073


class TestSelection:
    def test_customer_young_and_done_are_excluded(self):
        tickets = fixture_tickets()
        selected, excluded, eligible = select_sample(
            tickets,
            SelectionConfig(size=20, aged_days=90, seed=18094),
            AS_OF,
        )
        keys = {item.ticket.key for item in selected}
        assert "RHDHBUGS-1003" not in keys
        assert "RHDHBUGS-1004" not in keys
        assert "RHDHBUGS-1005" not in keys
        assert "RHDHBUGS-1008" not in keys
        assert "RHDHBUGS-1012" not in keys
        assert eligible >= len(selected)
        reasons = {item["key"]: item["reason"] for item in excluded}
        assert reasons["RHDHBUGS-1003"].startswith("customer-linked")
        assert reasons["RHDHBUGS-1008"].startswith("younger than 90d")

    def test_stratified_selection_is_stable(self):
        tickets = fixture_tickets()
        first, _, _ = select_sample(
            tickets, SelectionConfig(size=5, aged_days=90, seed=18094), AS_OF
        )
        second, _, _ = select_sample(
            tickets, SelectionConfig(size=5, aged_days=90, seed=18094), AS_OF
        )
        assert [item.ticket.key for item in first] == [item.ticket.key for item in second]

    def test_controls_are_appended_and_flagged(self):
        selected, _, _ = select_sample(
            fixture_tickets(),
            SelectionConfig(
                size=3,
                aged_days=90,
                seed=18094,
                controls=[
                    Control(key="RHDHBUGS-1009", label="still-valid"),
                    Control(key="RHDHBUGS-1010", label="duplicate"),
                ],
            ),
            AS_OF,
        )
        controls = [item for item in selected if item.kind == "control"]
        assert {item.ticket.key for item in controls} == {"RHDHBUGS-1009", "RHDHBUGS-1010"}
        assert {item.control_label for item in controls} == {"still-valid", "duplicate"}

    def test_done_control_is_selected_without_an_exclusion_entry(self):
        selected, excluded, _ = select_sample(
            fixture_tickets(),
            SelectionConfig(
                size=1,
                aged_days=90,
                seed=18094,
                controls=[Control(key="RHDHBUGS-1012", label="done-control")],
            ),
            AS_OF,
        )
        controls = [item for item in selected if item.kind == "control"]
        assert [item.ticket.key for item in controls] == ["RHDHBUGS-1012"]
        assert all(item["key"] != "RHDHBUGS-1012" for item in excluded)

    def test_customer_control_is_refused(self):
        selected, excluded, _ = select_sample(
            fixture_tickets(),
            SelectionConfig(
                size=1,
                aged_days=90,
                seed=18094,
                controls=[Control(key="RHDHBUGS-1003", label="customer")],
            ),
            AS_OF,
        )
        assert all(item.ticket.key != "RHDHBUGS-1003" for item in selected)
        assert any(
            item["key"] == "RHDHBUGS-1003" and "customer-linked" in item["reason"]
            for item in excluded
        )


class TestDuplicates:
    def test_duplicate_pair_ranks_in_top_candidates(self):
        tickets = by_key()
        candidates = rank_candidates(tickets["RHDHBUGS-1001"], tickets.values(), limit=3)
        keys = [candidate.key for candidate in candidates]
        assert "RHDHBUGS-1002" in keys
        assert candidates[0].score >= 0.70

    def test_explicit_duplicate_link_is_explained(self):
        tickets = by_key()
        candidate = score_candidate(tickets["RHDHBUGS-1010"], tickets["RHDHBUGS-1009"])
        assert any("outward Duplicate link" in reason for reason in candidate.reasons)
        assert candidate.score > 0.70

    def test_identical_tickets_score_near_one(self):
        ticket = Ticket(
            key="RHDHBUGS-1",
            summary="Helm install fails with release not found",
            description="Error: release: not found",
            team="RHDH Install",
            components=["Helm Chart"],
        )
        same = Ticket(
            key="RHDHBUGS-2",
            summary="Helm install fails with release not found",
            description="Error: release: not found",
            team="RHDH Install",
            components=["Helm Chart"],
        )
        assert score_candidate(ticket, same).score >= 0.95
        assert score_candidate(ticket, same).score >= DUPLICATE_CLOSE_THRESHOLD

    def test_distinctive_phrases_prefer_error_text(self):
        phrases = distinctive_phrases(by_key()["RHDHBUGS-1001"])
        assert phrases
        assert any("release" in phrase.lower() for phrase in phrases)

    def test_reverse_duplicate_link_cannot_reach_the_close_floor(self):
        tickets = by_key()
        candidate = score_candidate(tickets["RHDHBUGS-1009"], tickets["RHDHBUGS-1010"])
        assert candidate.score < DUPLICATE_CLOSE_THRESHOLD
        assert "candidate duplicates this ticket" in candidate.reasons


class TestPolicy:
    def test_missing_assessment_is_unclear_and_asks_for_repro(self):
        packet = evaluate_packet(by_key()["RHDHBUGS-1007"], [], None)
        assert packet.disposition == "unclear"
        assert packet.action == "needs_repro"
        assert "reproduction" in packet.proposed_comment.lower()

    def test_still_valid_keeps_open_with_direct_evidence(self):
        assessment = load_assessment(str(FIXTURES / "assessments" / "RHDHBUGS-1001.json"))
        packet = evaluate_packet(by_key()["RHDHBUGS-1001"], [], assessment)
        assert packet.disposition == "still_valid"
        assert packet.action == "keep_open"
        assert packet.confidence >= 0.9

    def test_duplicate_below_lexical_floor_only_comments(self):
        assessment = load_assessment(str(FIXTURES / "assessments" / "RHDHBUGS-1002.json"))
        candidates = rank_candidates(by_key()["RHDHBUGS-1002"], fixture_tickets(), limit=3)
        packet = evaluate_packet(by_key()["RHDHBUGS-1002"], candidates, assessment)
        assert packet.disposition == "duplicate"
        assert packet.action == "comment_only"
        assert "not a close proposal" in packet.proposed_comment

    def test_explicit_duplicate_link_clears_close_gate(self):
        assessment = load_assessment(str(FIXTURES / "assessments" / "RHDHBUGS-1010.json"))
        candidates = rank_candidates(by_key()["RHDHBUGS-1010"], fixture_tickets(), limit=3)
        packet = evaluate_packet(by_key()["RHDHBUGS-1010"], candidates, assessment)
        assert packet.explicit_duplicate_link is True
        assert packet.action == "propose_close_duplicate"
        assert packet.target == "RHDHBUGS-1009"
        assert packet.verification_errors == []

    def test_inward_duplicate_link_does_not_clear_close_gate(self):
        # "is duplicated by" means the linked ticket is the duplicate; the
        # queried ticket is canonical and must stay open. The lexical score for
        # RHDHBUGS-1002 is below the floor, so the inward link must not rescue it.
        ticket = by_key()["RHDHBUGS-1002"]
        ticket.links = [Link(type="Duplicate", key="RHDHBUGS-1001", direction="inward")]
        assessment = load_assessment(str(FIXTURES / "assessments" / "RHDHBUGS-1002.json"))
        candidates = rank_candidates(ticket, fixture_tickets(), limit=3)
        packet = evaluate_packet(ticket, candidates, assessment)
        assert packet.explicit_duplicate_link is False
        assert packet.action == "comment_only"

    def test_customer_ticket_never_gets_a_close_action(self):
        ticket = by_key()["RHDHBUGS-1003"]
        ticket.links.append(Link(type="Duplicate", key="RHDHBUGS-1001"))
        assessment = Assessment(
            key=ticket.key,
            disposition="duplicate",
            duplicate_of="RHDHBUGS-1001",
            evidence=[
                Evidence(
                    type="jira",
                    ref="RHDHBUGS-1001",
                    why="Same error text.",
                    strength="direct",
                )
            ],
            independent_passes=2,
            agreement=True,
        )
        packet = evaluate_packet(ticket, [], assessment)
        assert packet.customer_signals
        assert not packet.action.startswith("propose_close")
        assert any("customer-linked" in gap for gap in packet.gaps)

    def test_one_review_pass_blocks_close(self):
        assessment = load_assessment(str(FIXTURES / "assessments" / "RHDHBUGS-1010.json"))
        assessment.independent_passes = 1
        candidates = rank_candidates(by_key()["RHDHBUGS-1010"], fixture_tickets(), limit=3)
        packet = evaluate_packet(by_key()["RHDHBUGS-1010"], candidates, assessment)
        assert packet.action == "comment_only"

    def test_released_fix_with_pr_closes(self):
        assessment = load_assessment(str(FIXTURES / "assessments" / "RHDHBUGS-1006.json"))
        packet = evaluate_packet(by_key()["RHDHBUGS-1006"], [], assessment)
        assert packet.disposition == "already_fixed"
        assert packet.action == "propose_close_fixed"
        assert "2.1.0" in packet.proposed_comment

    def test_done_ticket_never_gets_a_close_action(self):
        assessment = load_assessment(str(FIXTURES / "assessments" / "RHDHBUGS-1006.json"))
        packet = evaluate_packet(by_key()["RHDHBUGS-1012"], [], assessment)
        assert packet.disposition == "already_fixed"
        assert packet.action == "comment_only"
        assert any("already Done" in gap for gap in packet.gaps)

    def test_unreleased_fix_only_comments(self):
        assessment = load_assessment(str(FIXTURES / "assessments" / "RHDHBUGS-1006.json"))
        assessment.fix_released = False
        packet = evaluate_packet(by_key()["RHDHBUGS-1006"], [], assessment)
        assert packet.action == "comment_only"
        assert "Do not close" in packet.proposed_comment

    def test_invalid_evidence_is_dropped_and_fails_closed(self):
        document = json.loads(
            (FIXTURES / "assessments" / "RHDHBUGS-1006.json").read_text(encoding="utf-8")
        )
        document["evidence"] = [{"type": "pr", "why": "missing ref"}]
        from bugtriage.policy import parse_assessment

        assessment = parse_assessment(document)
        assert assessment.invalid_evidence
        packet = evaluate_packet(by_key()["RHDHBUGS-1006"], [], assessment)
        assert packet.action != "propose_close_fixed"
        assert any("lacked a citation" in gap for gap in packet.gaps)

    def test_verifier_rejects_close_without_direct_evidence(self):
        packet = Packet(
            key="RHDHBUGS-1",
            summary="x",
            status="Backlog",
            disposition="already_fixed",
            confidence=0.95,
            confidence_basis=[],
            action="propose_close_fixed",
            recommended_step="close",
            evidence=[
                Evidence(type="jira", ref="RHDHBUGS-2", why="support", strength="supporting")
            ],
            duplicate_candidates=[],
            independent_passes=2,
            agreement=True,
        )
        errors = verify_packet(packet, by_key()["RHDHBUGS-1006"])
        assert any("direct evidence" in error for error in errors)


class TestReport:
    def _packet(self):
        assessment = load_assessment(str(FIXTURES / "assessments" / "RHDHBUGS-1010.json"))
        candidates = rank_candidates(by_key()["RHDHBUGS-1010"], fixture_tickets(), limit=3)
        return evaluate_packet(by_key()["RHDHBUGS-1010"], candidates, assessment)

    def test_packet_marks_dry_run_and_never_posts(self):
        rendered = render_packet(self._packet(), by_key()["RHDHBUGS-1010"])
        assert "Dry run" in rendered
        assert "Proposed Jira comment (not posted)" in rendered
        assert "propose_close_duplicate" in rendered

    def test_batch_report_has_method_and_controls(self):
        packet = self._packet()
        rendered = render_report(
            [packet],
            by_key(),
            generated_at="2026-11-09T10:00:00+00:00",
            as_of=AS_OF,
            current_release="2.1.0",
            jql="project = RHDHBUGS",
            sample_size=1,
            control_count=1,
            corpus_size=12,
            excluded=[],
            selection={
                "RHDHBUGS-1010": {
                    "kind": "control",
                    "controlLabel": "duplicate",
                    "stratum": "RHDH Frontend Plugins & UI",
                }
            },
            thresholds={"duplicate": 0.85, "fixed": 0.80, "obsolete": 0.80},
        )
        assert "Dry run" in rendered
        assert "Control" in rendered
        assert "0.85" in rendered
        assert "nothing in this artifact was posted" in rendered.lower()

    def test_csv_has_one_row_per_packet(self):
        packet = self._packet()
        csv_text = render_summary_csv([packet], {"RHDHBUGS-1010": {"kind": "control"}})
        assert len(csv_text.strip().splitlines()) == 2
        assert "RHDHBUGS-1010" in csv_text

    def test_manifest_declares_no_writes(self):
        packet = self._packet()
        manifest = render_manifest(
            generated_at="2026-11-09T10:00:00+00:00",
            as_of=AS_OF,
            current_release="2.1.0",
            jql="project = RHDHBUGS",
            input_path="issues.json",
            sample_path="sample.json",
            assessments_path="assessments",
            output_path="out",
            corpus_size=12,
            sample_size=1,
            control_count=1,
            packets=[packet],
            thresholds={"duplicate": 0.85},
            policy_version=1,
        )
        assert manifest["dryRun"] is True
        assert manifest["writes"] == []
        assert manifest["counts"]["closeProposals"] == 1


class TestRun:
    def test_end_to_end_outputs(self, tmp_path):
        sample = sample_manifest(tmp_path)
        out = tmp_path / "run"
        result = run(
            RunConfig(
                input_path=str(FIXTURES / "issues.json"),
                output_dir=str(out),
                sample_path=str(sample),
                assessments_dir=str(FIXTURES / "assessments"),
                current_release="2.1.0",
                as_of="2026-11-09",
            )
        )
        assert len(result.packets) == 7
        for name in ("report.md", "packets.json", "summary.csv", "manifest.json"):
            assert (out / name).is_file()
        assert (out / "proposed" / "RHDHBUGS-1001.md").is_file()
        packets = json.loads((out / "packets.json").read_text(encoding="utf-8"))
        assert packets["dryRun"] is True
        close = [item for item in packets["packets"] if item["action"].startswith("propose_close")]
        assert {item["key"] for item in close} == {"RHDHBUGS-1006", "RHDHBUGS-1010"}
        assert all(item["evidence"] for item in close)
        assert not any(
            item["action"].startswith("propose_close") and item["customerSignals"]
            for item in packets["packets"]
        )

    def test_missing_sample_key_fails_closed(self, tmp_path):
        sample = tmp_path / "sample.json"
        sample.write_text(json.dumps({"tickets": [{"key": "RHDHBUGS-9999"}]}), encoding="utf-8")
        with pytest.raises(RunError, match="missing from the export"):
            run(
                RunConfig(
                    input_path=str(FIXTURES / "issues.json"),
                    output_dir=str(tmp_path / "run"),
                    sample_path=str(sample),
                )
            )

    def test_malformed_assessment_aborts(self, tmp_path):
        sample = sample_manifest(tmp_path)
        assessments = tmp_path / "assessments"
        assessments.mkdir()
        (assessments / "RHDHBUGS-1001.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(RunError, match="invalid assessment"):
            run(
                RunConfig(
                    input_path=str(FIXTURES / "issues.json"),
                    output_dir=str(tmp_path / "run"),
                    sample_path=str(sample),
                    assessments_dir=str(assessments),
                    as_of="2026-11-09",
                )
            )


class TestEvaluate:
    def test_evaluation_reports_no_false_close(self, tmp_path):
        sample = sample_manifest(tmp_path)
        out = tmp_path / "run"
        run(
            RunConfig(
                input_path=str(FIXTURES / "issues.json"),
                output_dir=str(out),
                sample_path=str(sample),
                assessments_dir=str(FIXTURES / "assessments"),
                as_of="2026-11-09",
            )
        )
        packets = json.loads((out / "packets.json").read_text(encoding="utf-8"))
        observed = [
            Packet(
                key=item["key"],
                summary=item["summary"],
                status=item["status"],
                disposition=item["disposition"],
                confidence=item["confidence"],
                confidence_basis=item["confidenceBasis"],
                action=item["action"],
                recommended_step=item["recommendedStep"],
                evidence=[],
                duplicate_candidates=[],
                target=item.get("target", ""),
            )
            for item in packets["packets"]
        ]
        result = evaluate(observed, load_truth(str(FIXTURES / "truth.json")))
        assert result.false_closes == []
        assert result.precision["duplicate"] == 1.0
        assert result.precision["already_fixed"] == 1.0
        assert result.coverage == 1.0
        assert result.decision_ready_rate >= 0.8

    def test_unsupported_disposition_is_not_rendered_as_zero_percent(self):
        packet = Packet(
            key="RHDHBUGS-1001",
            summary="still valid",
            status="Backlog",
            disposition="still_valid",
            confidence=0.8,
            confidence_basis=[],
            action="keep_open",
            recommended_step="keep open",
            evidence=[],
            duplicate_candidates=[],
            target="",
        )
        result = evaluate([packet], {"RHDHBUGS-1001": {"disposition": "still_valid"}})
        rendered = render_evaluation(result)
        assert "`duplicate`" not in rendered
        assert "`already_fixed`" not in rendered

    def test_false_close_is_detected(self):
        packet = Packet(
            key="RHDHBUGS-1001",
            summary="still valid",
            status="Backlog",
            disposition="duplicate",
            confidence=0.9,
            confidence_basis=[],
            action="propose_close_duplicate",
            recommended_step="close",
            evidence=[],
            duplicate_candidates=[],
            target="RHDHBUGS-1002",
        )
        result = evaluate([packet], {"RHDHBUGS-1001": {"disposition": "still_valid"}})
        assert len(result.false_closes) == 1


class TestAdapters:
    def test_acli_json_shapes(self):
        assert parse_acli_json('[{"key": "A-1"}]') == [{"key": "A-1"}]
        assert parse_acli_json('{"issues": [{"key": "A-1"}]}') == [{"key": "A-1"}]
        with pytest.raises(JiraAdapterError):
            parse_acli_json("not json")
        with pytest.raises(JiraAdapterError):
            parse_acli_json('{"value": 1}')

    def test_acli_search_is_read_only_and_paginates(self, monkeypatch):
        captured = {}

        def fake_run(args, **kwargs):
            captured["args"] = args

            class Result:
                returncode = 0
                stdout = '[{"key": "RHDHBUGS-1"}]'
                stderr = ""

            return Result()

        monkeypatch.setattr(subprocess, "run", fake_run)
        issues = search_acli("project = RHDHBUGS")
        assert issues == [{"key": "RHDHBUGS-1"}]
        assert captured["args"][:4] == ["acli", "jira", "workitem", "search"]
        assert "--paginate" in captured["args"]
        assert "edit" not in captured["args"]
        assert "create" not in captured["args"]

    def test_forge_cache_and_normalization(self, tmp_path):
        cache_path = tmp_path / "gh.json"
        cache_path.write_text(
            json.dumps(
                {
                    "pulls": {
                        "https://github.com/x/y/pull/1": {
                            "state": "MERGED",
                            "mergedAt": "2026-01-01T00:00:00Z",
                            "mergeCommit": {"oid": "abc1234"},
                            "baseRefName": "main",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        cache = load_cache(str(cache_path))
        pull = lookup_pr("https://github.com/x/y/pull/1", cache, use_gh=False)
        assert pull["merged"] is True
        assert pull["mergeCommit"] == "abc1234"
        assert normalize_pr({"state": "OPEN"}, "u")["merged"] is False

    def test_collect_writes_one_evidence_file_per_ticket(self, tmp_path):
        sample = sample_manifest(tmp_path)
        out = tmp_path / "evidence"
        written = collect(
            CollectConfig(
                input_path=str(FIXTURES / "issues.json"),
                sample_path=str(sample),
                output_dir=str(out),
                use_gh=False,
            )
        )
        assert len(written) == 7
        assert (out / "index.json").is_file()
        evidence = json.loads((out / "RHDHBUGS-1006.json").read_text(encoding="utf-8"))
        assert evidence["pullRequests"][0]["url"].endswith("/pull/999")
        assert evidence["kind"] == "aged"


class TestDryRunInvariant:
    def test_no_write_verbs_in_scripts(self):
        forbidden = [
            '["jira", "workitem", "edit"',
            '"workitem", "edit"',
            '"workitem", "create"',
            '"workitem", "comment"',
            '"workitem", "transition"',
            '"gh", "pr", "merge"',
            '"gh", "pr", "comment"',
            '"gh", "pr", "create"',
        ]
        for path in (SKILL_ROOT / "scripts").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for value in forbidden:
                assert value not in text, f"{path} contains a write verb: {value}"

    def test_cli_has_no_apply_or_post_command(self):
        parser = cli.build_parser()
        help_text = parser.format_help()
        assert "apply" not in help_text.lower()
        assert "post" not in help_text.lower()

    def test_run_manifest_records_zero_writes(self, tmp_path):
        sample = sample_manifest(tmp_path)
        out = tmp_path / "run"
        result = run(
            RunConfig(
                input_path=str(FIXTURES / "issues.json"),
                output_dir=str(out),
                sample_path=str(sample),
                assessments_dir=str(FIXTURES / "assessments"),
                as_of="2026-11-09",
            )
        )
        assert result.manifest["writes"] == []
        assert result.manifest["dryRun"] is True


class TestCatalogMembership:
    def test_catalog_entry_and_harness_metadata(self):
        catalog = json.loads(
            (
                PROJECT_ROOT / "skills" / "meta" / "setup-rhdh-skills" / "assets" / "catalog.json"
            ).read_text(encoding="utf-8")
        )
        entry = next(item for item in catalog["skills"] if item["name"] == "rhdh-bug-triage")
        assert entry["category"] == "jira"
        assert entry["invocation"] == "model"
        assert "rhdh-jira-api" in entry["requiresSkills"]
        assert (SKILL_ROOT / "agents" / "openai.yaml").is_file()
        assert (SKILL_ROOT / "TESTING.md").is_file()
