"""Rule-parity tests for the Jira lint scanner and plan executor.

The scanner carries the only copy of the lint rule set that runs without Jira, so
these tests pin the rules themselves: the exemptions, the release phases, the
action class each finding is handed to the remediation SOP with, and the mention
target the receipt comment addresses.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[2] / "skills" / "jira" / "rhdh-jira-lint" / "scripts"
)


def _load(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SKILL_SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scan():
    return _load("rhdh_lint_scan", "scan.py")


@pytest.fixture(scope="module")
def apply():
    return _load("rhdh_lint_apply", "apply.py")


FIELDS = {
    "team": "cf_team",
    "size": "cf_size",
    "story_points": "cf_points",
    "rn_type": "cf_rn_type",
    "rn_text": "cf_rn_text",
    "rn_status": "cf_rn_status",
}

CALENDAR = {
    "1.10.0": {
        "feature_freeze": "2026-01-05",
        "code_freeze": "2026-01-26",
        "ga_push": "2026-02-17",
    }
}


def issue(key: str = "RHIDP-1", **fields):
    base = {
        "summary": "A thing",
        "status": {"name": "New"},
        "issuetype": {"name": "Story"},
        "project": {"key": "RHIDP"},
        "priority": {"name": "Major"},
        "components": [{"name": "Catalog"}],
        "fixVersions": [],
        "labels": [],
        "description": "Acceptance Criteria:\n- one\n- two",
    }
    base.update(fields)
    return {"key": key, "fields": base}


def ctx(**overrides):
    payload = {
        "fields": FIELDS,
        "calendar": CALENDAR,
        "today": date(2026, 1, 10),
        "parents": {},
        "children": {},
    }
    payload.update(overrides)
    return payload


def rules(scan, item, context=None):
    return [finding["rule"] for finding in scan.evaluate(item, context or ctx())]


def test_missing_component_and_priority_are_findings(scan):
    item = issue(components=[], priority={"name": "Undefined"}, **{"cf_points": 3})
    findings = scan.evaluate(item, ctx())

    assert {finding["rule"] for finding in findings} == {"LINT-COMPONENT", "LINT-PRIORITY"}
    assert all(finding["action"] == "choose" for finding in findings)
    assert all(finding["proposed"] is None for finding in findings)


def test_parent_supplies_component_and_priority(scan):
    parent = issue(
        "RHIDP-100",
        issuetype={"name": "Epic"},
        components=[{"name": "Catalog"}, {"name": "Search"}],
        priority={"name": "Critical"},
    )
    item = issue(components=[], priority={"name": "Undefined"}, parent={"key": "RHIDP-100"})
    context = ctx(parents={"RHIDP-100": parent})

    findings = {finding["rule"]: finding for finding in scan.evaluate(item, context)}

    assert findings["LINT-COMPONENT"]["action"] == "derive"
    assert findings["LINT-COMPONENT"]["proposed"] == {
        "fields": {"components": [{"name": "Catalog"}, {"name": "Search"}]}
    }
    assert findings["LINT-PRIORITY"]["proposed"] == {"fields": {"priority": {"name": "Critical"}}}


def test_docs_team_is_exempt_from_size_and_points(scan):
    epic = issue(
        "RHIDP-2",
        issuetype={"name": "Epic"},
        **{"cf_team": {"name": "RHIDP - Documentation"}},
    )
    story = issue(
        "RHIDP-3",
        **{"cf_team": {"name": "RHIDP - Documentation"}},
    )

    assert "LINT-SIZE" not in rules(scan, epic)
    assert "LINT-POINTS" not in rules(scan, story)


def test_release_component_is_exempt_from_freeze_and_release_notes(scan):
    item = issue(
        "RHIDP-4",
        components=[{"name": "Release"}],
        priority={"name": "Major"},
        fixVersions=[{"name": "1.10.0"}],
        issuetype={"name": "Feature"},
    )

    found = rules(scan, item)

    assert "LINT-FF-PRIORITY" not in found
    assert "LINT-RN-TYPE" not in found


@pytest.mark.parametrize(
    "fields",
    [
        {"issuetype": {"name": "Story", "subtask": True}},
        {"status": {"name": "Release Pending"}},
        {"status": {"name": "Closed"}},
        {"issuetype": {"name": "Outcome"}},
        {"summary": "[Test Execution] nightly"},
    ],
)
def test_excluded_issue_shapes_produce_nothing(scan, fields):
    item = issue(components=[], priority={"name": "Undefined"}, **fields)
    assert scan.evaluate(item, ctx()) == []


@pytest.mark.parametrize(
    ("today", "priority", "expected"),
    [
        (date(2026, 1, 10), "Major", "LINT-FF-PRIORITY"),
        (date(2026, 1, 10), "Critical", None),
        (date(2026, 1, 27), "Critical", "LINT-CF-PRIORITY"),
        (date(2026, 1, 27), "Blocker", None),
    ],
)
def test_freeze_phases_escalate_the_right_priorities(scan, today, priority, expected):
    item = issue(priority={"name": priority}, fixVersions=[{"name": "1.10.0"}])
    found = rules(scan, item, ctx(today=today))

    if expected is None:
        assert not {"LINT-FF-PRIORITY", "LINT-CF-PRIORITY"} & set(found)
    else:
        assert expected in found


def test_ga_push_flags_an_open_issue(scan):
    item = issue(fixVersions=[{"name": "1.10.0"}])
    findings = {
        finding["rule"]: finding for finding in scan.evaluate(item, ctx(today=date(2026, 3, 1)))
    }

    assert findings["LINT-GA-OPEN"]["action"] == "escalate"
    assert findings["LINT-GA-OPEN"]["evidence"]["options"]


def test_multiple_fix_versions_keep_the_single_active_release(scan):
    item = issue(fixVersions=[{"name": "1.9.0"}, {"name": "1.10.0"}])
    findings = {finding["rule"]: finding for finding in scan.evaluate(item, ctx())}

    assert findings["LINT-FIXVERSION-MULTI"]["action"] == "derive"
    assert findings["LINT-FIXVERSION-MULTI"]["proposed"] == {
        "fields": {"fixVersions": [{"name": "1.10.0"}]}
    }


def test_release_note_gaps_after_feature_freeze(scan):
    item = issue(
        issuetype={"name": "Feature"},
        fixVersions=[{"name": "1.10.0"}],
        **{"cf_rn_text": {"type": "doc", "version": 1, "content": []}},
    )
    findings = {finding["rule"]: finding for finding in scan.evaluate(item, ctx())}

    assert {"LINT-RN-TYPE", "LINT-RN-TEXT"} <= set(findings)
    assert findings["LINT-RN-TYPE"]["action"] == "classify"
    assert findings["LINT-RN-TEXT"]["action"] == "draft"


def test_release_note_not_required_skips_text_and_status(scan):
    item = issue(
        issuetype={"name": "Feature"},
        fixVersions=[{"name": "1.10.0"}],
        **{"cf_rn_type": {"value": "Release Note Not Required"}},
    )
    found = rules(scan, item)

    assert "LINT-RN-TEXT" not in found
    assert "LINT-RN-STATUS" not in found


def test_status_is_proposed_once_the_type_is_known(scan):
    item = issue(
        issuetype={"name": "Bug"},
        fixVersions=[{"name": "1.10.0"}],
        **{"cf_rn_type": {"value": "Bug Fix"}},
    )
    findings = {finding["rule"]: finding for finding in scan.evaluate(item, ctx())}

    assert findings["LINT-RN-STATUS"]["proposed"] == {
        "fields": {"cf_rn_status": {"value": "Proposed"}}
    }


def test_active_waiver_is_reported_separately(scan):
    item = issue(components=[], labels=["hygiene-waived-2026-06"])
    findings = scan.evaluate(item, ctx())

    assert findings
    assert all(finding["waived"] for finding in findings)


def test_expired_waiver_becomes_a_review(scan):
    item = issue(components=[], labels=["hygiene-waived-2025-12"])
    findings = scan.evaluate(item, ctx(today=date(2026, 1, 10)))

    assert findings
    assert all(finding["action"] == "review-waiver" for finding in findings)


def test_set_fields_produce_no_findings(scan):
    item = issue(
        fixVersions=[{"name": "1.10.0"}],
        **{
            "cf_points": 3,
            "cf_rn_type": {"value": "Feature"},
            "cf_rn_text": {"type": "doc", "version": 1, "content": [{"type": "paragraph"}]},
            "cf_rn_status": {"value": "Proposed"},
        },
    )
    # Still in Development, so the freeze and release-note rules stay quiet.
    assert scan.evaluate(item, ctx(today=date(2025, 12, 1))) == []


def test_acceptance_criteria_count_reads_adf_and_wiki(scan):
    plain = "Acceptance Criteria:\n- one\n- two\n- three"
    assert scan.acceptance_criteria_count(plain) == 3

    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Acceptance Criteria:"}],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "a"}]}
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "b"}]}
                        ],
                    },
                ],
            },
        ],
    }
    assert scan.acceptance_criteria_count(scan._flatten_adf(adf)) == 2


def test_release_calendar_parsing(tmp_path, scan):
    path = tmp_path / "release_calendar.yaml"
    path.write_text(
        "releases:\n"
        '  "1.10.0":\n'
        '    feature_freeze: "2026-01-05"\n'
        '    code_freeze: "2026-01-26"\n'
        '    ga_push: "2026-02-17"\n'
        '    backstage_version: "1.49.0"\n'
        '  "1.11.0":\n'
        '    feature_freeze: "TBD"\n',
        encoding="utf-8",
    )
    calendar, problems = scan.load_release_calendar(path)

    assert calendar["1.10.0"]["code_freeze"] == "2026-01-26"
    assert scan.release_phase("1.10.0", calendar, date(2026, 1, 10))[0] == "Feature Freeze"
    assert [problem["version"] for problem in problems] == ["1.11.0"]


def test_json_calendar_maps_ga_announce_to_ga_push(tmp_path, scan):
    path = tmp_path / "dates.json"
    path.write_text(
        json.dumps(
            {
                "releases": [
                    {
                        "version": "1.10.0",
                        "issue_key": "RHDHPLAN-1",
                        "feature_freeze": "2026-01-05",
                        "code_freeze": "2026-01-26",
                        "doc_freeze": "2026-01-20",
                        "go_no_go": "2026-02-10",
                        "ga_announce": "2026-02-17",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    calendar, problems = scan.load_release_calendar(path)

    assert problems == []
    assert calendar["1.10.0"]["ga_push"] == "2026-02-17"


def test_json_calendar_reports_tbd_versions(tmp_path, scan):
    path = tmp_path / "dates.json"
    path.write_text(
        json.dumps(
            {
                "2.2.0": {
                    "feature_freeze": "TBD",
                    "code_freeze": None,
                    "ga_push": None,
                }
            }
        ),
        encoding="utf-8",
    )
    calendar, problems = scan.load_release_calendar(path)

    assert calendar == {}
    assert problems[0]["version"] == "2.2.0"
    assert set(problems[0]["missing"]) == {"feature_freeze", "code_freeze", "ga_push"}


def test_calendar_discovery_prefers_the_flag_then_the_environment(tmp_path, scan, monkeypatch):
    explicit = tmp_path / "explicit.yaml"
    monkeypatch.setenv(scan.CALENDAR_ENV, str(tmp_path / "env.yaml"))
    assert scan.discover_calendar(str(explicit)) == str(explicit)

    monkeypatch.chdir(tmp_path)
    assert scan.discover_calendar(None) == str(tmp_path / "env.yaml")

    monkeypatch.delenv(scan.CALENDAR_ENV)
    (tmp_path / scan.CALENDAR_FILE).write_text("releases:\n")
    assert scan.discover_calendar(None) == scan.CALENDAR_FILE


def test_mention_prefers_the_assignee_then_the_reporter(scan):
    assigned = issue(
        assignee={"accountId": "a1", "displayName": "Jane"},
        reporter={"accountId": "r1", "displayName": "Sam"},
    )
    assert scan.mention_for(assigned["fields"]) == {
        "accountId": "a1",
        "displayName": "Jane",
        "role": "assignee",
    }

    unassigned = issue(reporter={"accountId": "r1", "displayName": "Sam"})
    assert scan.mention_for(unassigned["fields"])["role"] == "reporter"

    assert scan.mention_for(issue()["fields"]) is None


def test_component_order_does_not_fail_verification(apply):
    expected = [{"name": "Search"}, {"name": "Catalog"}]
    actual = [{"name": "Catalog"}, {"name": "Search"}]

    assert apply.values_match(expected, actual)


def test_adf_release_note_text_verifies_by_content(apply):
    expected = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Users can now do X."}]}
        ],
    }
    actual = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Users can now do X."}]},
            {"type": "paragraph"},
        ],
    }

    assert apply.values_match(expected, actual)


def test_precondition_requires_the_field_to_still_be_empty(apply):
    assert apply.precondition_holds("empty", None)
    assert apply.precondition_holds("empty", [])
    assert not apply.precondition_holds("empty", [{"name": "Catalog"}])
    assert apply.precondition_holds("any", "whatever")


def test_comment_carries_the_marker_the_lines_and_the_mention(apply):
    adf = apply.build_comment_adf(
        ["Component -> Catalog (inherited from RHIDP-1100)."],
        {"accountId": "a1", "displayName": "Jane", "role": "assignee"},
    )
    text = apply.comment_text(adf)

    assert apply.COMMENT_MARKER in text
    assert "inherited from RHIDP-1100" in text
    assert "@Jane" in text
    mention = adf["content"][-1]["content"][0]
    assert mention == {"type": "mention", "attrs": {"id": "a1", "text": "@Jane"}}


def test_comment_without_a_mention_still_has_the_marker(apply):
    adf = apply.build_comment_adf(["Points -> 3."], None)

    assert apply.COMMENT_MARKER in apply.comment_text(adf)
    assert all(node["type"] == "paragraph" for node in adf["content"])


def test_comment_batch_id_is_stable_and_content_sensitive(apply):
    mention = {"accountId": "a1", "displayName": "Jane"}
    first = apply.batch_id(["Points -> 3.", "Component -> Catalog."], mention)
    retry = apply.batch_id(["Points -> 3.", "Component -> Catalog."], mention)
    changed = apply.batch_id(["Points -> 5.", "Component -> Catalog."], mention)
    other_person = apply.batch_id(
        ["Points -> 3.", "Component -> Catalog."],
        {"accountId": "a2", "displayName": "Sam"},
    )

    assert first == retry
    assert first != changed
    assert first != other_person
    adf = apply.build_comment_adf(["Points -> 3."], mention)
    assert f"({apply.batch_id(['Points -> 3.'], mention)})" in apply.comment_text(adf)


def test_plan_validation_rejects_empty_comments(apply):
    with pytest.raises(apply.ApplyError):
        apply.validate_plan({"comments": [{"key": "RHIDP-1", "lines": []}]})

    with pytest.raises(apply.ApplyError):
        apply.validate_plan({"comments": [{"key": "RHIDP-1", "lines": ["ok"], "mention": {}}]})

    operations, comments = apply.validate_plan({"comments": [{"key": "RHIDP-1", "lines": ["ok"]}]})
    assert operations == []
    assert comments[0]["key"] == "RHIDP-1"


def test_default_jql_bounds_the_sweep(scan):
    import argparse

    args = argparse.Namespace(keys=None, jql=None, assignee=None, release=None)
    jql = scan.build_jql(args)

    assert "project in (RHIDP,RHDHPLAN,RHDHBUGS)" in jql
    assert "updated >= -365d" in jql

    args = argparse.Namespace(keys=None, jql=None, assignee="me", release=None)
    assert "assignee = currentUser()" in scan.build_jql(args)


def test_collect_separates_waived_findings(scan, monkeypatch):
    import argparse

    issues = [
        issue("RHIDP-1", components=[], priority={"name": "Major"}, **{"cf_points": 3}),
        issue(
            "RHIDP-2",
            components=[],
            priority={"name": "Major"},
            labels=["hygiene-waived-2026-06"],
            **{"cf_points": 3},
        ),
    ]

    monkeypatch.setattr(scan, "load_email_token", lambda: "bot@example.com:token")
    monkeypatch.setattr(scan, "resolve_fields", lambda base, credential: (FIELDS, []))
    monkeypatch.setattr(scan, "search_issues", lambda *args, **kwargs: (issues, False))
    monkeypatch.setattr(scan, "discover_calendar", lambda explicit: None)

    args = argparse.Namespace(
        jql=None,
        keys=None,
        assignee=None,
        team=None,
        release=None,
        release_calendar=None,
        today="2026-01-10",
        limit=500,
        page_size=100,
        include_waived=False,
    )
    report = scan.collect(args)

    assert report["scope"]["issues_scanned"] == 2
    assert [finding["key"] for finding in report["findings"]] == ["RHIDP-1"]
    assert [finding["key"] for finding in report["waived"]] == ["RHIDP-2"]
    assert report["summary"]["by_rule"] == {"LINT-COMPONENT": 1}
    assert any("release calendar" in warning for warning in report["warnings"])
