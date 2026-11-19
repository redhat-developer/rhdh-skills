"""Read-only fix guidance: every investigated bug names where a fix would land."""

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/jira/rhdh-bug-triage/scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bug_triage"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bugtriage.model import Ticket, load_export  # noqa: E402
from bugtriage.policy import (  # noqa: E402
    Evidence,
    evaluate,
    fix_plan_errors,
    parse_assessment,
)
from bugtriage.report import render_report  # noqa: E402
from bugtriage.run import RunConfig, RunError, run  # noqa: E402

SOURCE = "https://github.com/example/product/blob/abc123/handler.ts"
EVIDENCE = [
    Evidence("code", SOURCE, "The restricted upload path still rejects .md files.", "direct")
]


def plan(**overrides):
    data = {
        "approach": "Accept the notebook file-type set in the chat upload validator and share the error copy.",
        "areas": [
            {
                "repository": "example/product",
                "paths": ["plugins/chat/src/utils/attachment-utils.ts"],
            }
        ],
        "complexity": "small",
        "refs": [SOURCE],
    }
    data.update(overrides)
    return data


def test_valid_fix_plan_passes():
    assert fix_plan_errors(plan(), EVIDENCE, "still_valid") == []


def test_missing_fix_plan_is_rejected():
    assert fix_plan_errors({}, EVIDENCE, "still_valid") == [
        "fixPlan is missing; every investigated bug needs read-only fix guidance"
    ]
    assert fix_plan_errors({}, EVIDENCE, "unclear")


@pytest.mark.parametrize(
    "field,value",
    [
        ("approach", ""),
        ("approach", "   "),
        ("approach", None),
        ("complexity", ""),
        ("complexity", "easy"),
        ("complexity", None),
        ("areas", "plugins/chat"),
        ("areas", [{"repository": "", "paths": ["a.ts"]}]),
        ("areas", [{"repository": "example/product", "paths": "a.ts"}]),
        ("areas", [{"repository": "example/product", "paths": ["  "]}]),
        ("refs", ["not-a-ref"]),
        ("refs", "RHDHBUGS-1"),
    ],
)
def test_malformed_fix_plan_is_rejected(field, value):
    assert fix_plan_errors(plan(**{field: value}), EVIDENCE, "still_valid")


def test_fix_plan_refs_must_be_cited_evidence():
    uncited = "https://github.com/example/product/blob/abc123/other.ts"
    errors = fix_plan_errors(plan(refs=[uncited]), EVIDENCE, "still_valid")
    assert any("does not cite" in error for error in errors)


def test_complexity_none_is_only_for_resolution_dispositions():
    resolution = plan(approach="Close as a duplicate of the canonical report.", complexity="none")
    for disposition in ("duplicate", "already_fixed", "no_longer_valid"):
        assert fix_plan_errors(resolution, EVIDENCE, disposition) == []
    for disposition in ("still_valid", "needs_repro", "unclear"):
        assert fix_plan_errors(resolution, EVIDENCE, disposition)


def test_parse_assessment_reads_fix_plan():
    document = {
        "key": "RHDHBUGS-1010",
        "disposition": "still_valid",
        "evidence": [
            {"type": "code", "ref": SOURCE, "why": "Whitelist unchanged.", "strength": "direct"}
        ],
        "fixPlan": plan(),
    }
    assessment = parse_assessment(document)
    assert assessment.fix_plan["complexity"] == "small"
    assert assessment.fix_plan["areas"][0]["repository"] == "example/product"


def test_parse_assessment_tolerates_absent_fix_plan():
    assessment = parse_assessment({"key": "RHDHBUGS-1010", "disposition": "unclear"})
    assert assessment.fix_plan == {}


def test_packet_carries_fix_plan_and_report_renders_it(tmp_path):

    ticket = Ticket(
        key="RHDHBUGS-1010",
        summary="Chat rejects markdown attachments",
        status="New",
    )
    assessment = parse_assessment(
        {
            "key": "RHDHBUGS-1010",
            "disposition": "still_valid",
            "evidence": [
                {"type": "code", "ref": SOURCE, "why": "Whitelist unchanged.", "strength": "direct"}
            ],
            "fixPlan": plan(),
        }
    )
    packet = evaluate(ticket, [], assessment, current_release="2.1.0")
    assert packet.fix_plan["complexity"] == "small"
    report = render_report(
        [packet],
        {ticket.key: ticket},
        generated_at="2026-11-19T10:00:00+00:00",
        as_of=datetime(2026, 11, 19),
        current_release="2.1.0",
        jql="project = RHDHBUGS",
        sample_size=1,
        control_count=0,
        corpus_size=1,
        excluded=[],
        selection={"RHDHBUGS-1010": {"kind": "aged"}},
        thresholds={"duplicate": 0.85, "fixed": 0.80},
    )
    assert "Fix plan (read-only guidance" in report
    assert "attachment-utils.ts" in report
    assert "Complexity: small" in report
    assert "Read-only fix plans attached: 1 of 1" in report


def _assessment_with_plan(key: str, with_plan: bool) -> dict:
    document = {
        "key": key,
        "disposition": "still_valid",
        "evidence": [
            {"type": "code", "ref": SOURCE, "why": "Whitelist unchanged.", "strength": "direct"}
        ],
        "investigation": {
            "status": "completed",
            "release": "2.1.0",
            "scope": "The chat upload validation path.",
            "mechanism": "The validator rejects every extension outside json/yaml/text.",
            "requirements": [
                {
                    "statement": "Chat accepts the notebook file-type set.",
                    "result": "violated",
                    "observed": "Only json/yaml/text pass the check.",
                    "method": "code",
                    "refs": [SOURCE],
                }
            ],
            "blocker": "",
        },
    }
    if with_plan:
        document["fixPlan"] = plan()
    return document


class TestRequireFixPlan:
    def _config(self, tmp_path, with_plan: bool) -> "RunConfig":
        from bugtriage.run import build_sample_manifest
        from bugtriage.selection import SelectionConfig

        tickets = load_export(str(FIXTURES / "issues.json"))
        sample = build_sample_manifest(
            tickets,
            SelectionConfig(current_release="2.1.0", size=1, aged_days=90, seed=18094),
            datetime(2026, 11, 9),
            "project = RHDHBUGS",
        )
        selected = [entry["key"] for entry in sample["tickets"]]
        sample_path = tmp_path / "sample.json"
        sample_path.write_text(json.dumps(sample), encoding="utf-8")
        assessments = tmp_path / "assessments"
        assessments.mkdir()
        for key in selected:
            (assessments / f"{key}.json").write_text(
                json.dumps(_assessment_with_plan(key, with_plan))
            )
        return RunConfig(
            input_path=str(FIXTURES / "issues.json"),
            output_dir=str(tmp_path / "out"),
            sample_path=str(sample_path),
            assessments_dir=str(assessments),
            current_release="2.1.0",
            release_evidence="https://example.com/release-record",
            as_of="2026-11-09",
            require_fix_plan=True,
        )

    def test_run_without_fix_plan_fails_closed(self, tmp_path):
        with pytest.raises(RunError, match="fix plan incomplete"):
            run(self._config(tmp_path, with_plan=False))

    def test_run_with_fix_plan_succeeds_and_records_the_flag(self, tmp_path):
        result = run(self._config(tmp_path, with_plan=True))
        assert result.manifest["fixPlanRequired"] is True
        assert (result.output_dir / "audit" / "manifest.json").is_file()
        assert (result.output_dir / "report.md").is_file()
