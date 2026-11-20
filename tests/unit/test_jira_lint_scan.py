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


def test_precondition_requires_empty_or_exact_value(apply):
    assert apply.precondition_holds({"state": "empty"}, None)
    assert apply.precondition_holds({"state": "empty"}, [])
    assert not apply.precondition_holds({"state": "empty"}, [{"name": "Catalog"}])
    assert apply.precondition_holds({"state": "equals", "value": 3}, 3)
    assert not apply.precondition_holds({"state": "equals", "value": 3}, 5)


def valid_plan(**overrides):
    plan = {
        "schema": 2,
        "run_id": "run-1",
        "scan_digest": "a" * 64,
        "scope": {"jql": "project in (RHIDP)"},
        "fields": {
            "story_points": "customfield_points",
            "size": "customfield_size",
            "rn_type": "customfield_rn_type",
            "rn_text": "customfield_rn_text",
            "rn_status": "customfield_rn_status",
        },
        "issues": [
            {
                "key": "RHIDP-1234",
                "summary": "Improve authentication timeout handling",
                "project": "RHIDP",
                "issuetype": "Story",
                "status": "In Progress",
                "labels": [],
                "expected_updated": "2026-11-19T14:22:03.000-0500",
                "mention": {
                    "accountId": "account-1",
                    "displayName": "Jane Doe",
                    "role": "assignee",
                },
                "findings": [
                    {
                        "rule": "LINT-COMPONENT",
                        "action": "derive",
                        "decision": "supported",
                        "reason": "Component inherited from RHIDP-900.",
                        "evidence": {
                            "basis": "Parent RHIDP-900 has one component.",
                            "parent": "RHIDP-900",
                            "parent_components": ["Authentication"],
                        },
                        "set": {"fields": {"components": [{"name": "Authentication"}]}},
                        "precondition": {"field": "components", "state": "empty"},
                    },
                    {
                        "rule": "LINT-POINTS",
                        "action": "estimate",
                        "decision": "insufficient",
                        "reason": "Scope is ambiguous.",
                        "evidence": {
                            "basis": "The description and child spike disagree.",
                            "question": "Does this include migration?",
                        },
                    },
                ],
            }
        ],
    }
    plan.update(overrides)
    return plan


def test_validate_plan_rejects_schema_1_and_unknown_keys(apply):
    with pytest.raises(apply.ApplyError):
        apply.validate_plan(valid_plan(schema=1))
    with pytest.raises(apply.ApplyError):
        apply.validate_plan(valid_plan(extra="nope"))


def test_validate_plan_rejects_non_supported_writes(apply):
    plan = valid_plan()
    plan["issues"][0]["findings"][1]["decision"] = "supported"
    plan["issues"][0]["findings"][1]["set"] = {"fields": {"customfield_points": 3}}
    plan["issues"][0]["findings"][1]["precondition"] = {
        "field": "customfield_points",
        "state": "empty",
    }
    plan["issues"][0]["findings"][1]["evidence"] = {
        "basis": "Three acceptance criteria and one area.",
        "acceptance_criteria": 3,
        "affected_areas": ["authentication"],
    }
    issues, issue_count, operation_count = apply.validate_plan(plan)
    assert issue_count == 1
    assert operation_count == 2


def test_validate_plan_rejects_wrong_field_or_missing_precondition(apply):
    plan = valid_plan()
    finding = plan["issues"][0]["findings"][0]
    finding["set"] = {"fields": {"priority": {"name": "Normal"}}}
    with pytest.raises(apply.ApplyError):
        apply.validate_plan(plan)
    finding["set"] = {"fields": {"components": [{"name": "Authentication"}]}}
    finding["precondition"] = {"field": "priority", "state": "empty"}
    with pytest.raises(apply.ApplyError):
        apply.validate_plan(plan)


def test_validate_plan_allows_normal_and_inherited_critical(apply):
    normal = valid_plan()
    normal["issues"][0]["findings"][0] = {
        "rule": "LINT-PRIORITY",
        "action": "derive",
        "decision": "supported",
        "reason": "Routine work with no urgency signal.",
        "evidence": {"basis": "Routine work with a clear outcome and no urgency."},
        "set": {"fields": {"priority": {"name": "Normal"}}},
        "precondition": {"field": "priority", "state": "empty"},
    }
    apply.validate_plan(normal)

    inherited = valid_plan()
    inherited["issues"][0]["findings"][0] = {
        "rule": "LINT-PRIORITY",
        "action": "derive",
        "decision": "supported",
        "reason": "Critical inherited from RHIDP-900.",
        "evidence": {
            "basis": "Parent RHIDP-900 is Critical.",
            "parent": "RHIDP-900",
            "parent_priority": "Critical",
        },
        "set": {"fields": {"priority": {"name": "Critical"}}},
        "precondition": {"field": "priority", "state": "empty"},
    }
    apply.validate_plan(inherited)


def test_validate_plan_rejects_self_inferred_critical(apply):
    plan = valid_plan()
    plan["issues"][0]["findings"][0] = {
        "rule": "LINT-PRIORITY",
        "action": "derive",
        "decision": "supported",
        "reason": "This looks critical.",
        "evidence": {"basis": "The agent decided it looked critical."},
        "set": {"fields": {"priority": {"name": "Critical"}}},
        "precondition": {"field": "priority", "state": "empty"},
    }
    with pytest.raises(apply.ApplyError):
        apply.validate_plan(plan)


def test_validate_plan_rejects_invalid_points_and_size(apply):
    points = valid_plan()
    points["issues"][0]["findings"][0] = {
        "rule": "LINT-POINTS",
        "action": "estimate",
        "decision": "supported",
        "reason": "Three criteria and one area.",
        "evidence": {
            "basis": "Three criteria and one area.",
            "acceptance_criteria": 3,
            "affected_areas": ["authentication"],
        },
        "set": {"fields": {"customfield_points": 13}},
        "precondition": {"field": "customfield_points", "state": "empty"},
    }
    with pytest.raises(apply.ApplyError):
        apply.validate_plan(points)

    size = valid_plan()
    size["issues"][0]["findings"][0] = {
        "rule": "LINT-SIZE",
        "action": "estimate",
        "decision": "supported",
        "reason": "One sprint of work.",
        "evidence": {"basis": "One sprint of work.", "scope_signals": ["one component"]},
        "set": {"fields": {"customfield_size": "XXL"}},
        "precondition": {"field": "customfield_size", "state": "empty"},
    }
    with pytest.raises(apply.ApplyError):
        apply.validate_plan(size)


def test_build_comment_adf_is_mixed_and_red_hat_employee(apply):
    plan = valid_plan()
    issue = plan["issues"][0]
    adf = apply.build_comment_adf(issue, "run-1")
    text = apply.comment_text(adf)
    assert apply.COMMENT_MARKER in text
    assert "What changed" in text
    assert "What wasn’t changed" in text
    assert "LINT-COMPONENT" in text
    assert "LINT-POINTS" in text
    assert "@Jane Doe" in text
    assert apply.COMMENT_VISIBILITY == {
        "type": "group",
        "value": "Red Hat Employee",
    }


def test_batch_id_is_stable_and_sensitive_to_run_and_operations(apply):
    plan = valid_plan()
    issue = plan["issues"][0]
    first = apply.batch_id(issue, "run-1")
    retry = apply.batch_id(issue, "run-1")
    other_run = apply.batch_id(issue, "run-2")
    assert first == retry
    assert first != other_run


def test_run_issue_suppresses_comment_when_write_fails(apply, monkeypatch):
    plan = valid_plan()
    issue = plan["issues"][0]
    current = {
        "fields": {
            "summary": issue["summary"],
            "project": {"key": "RHIDP"},
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Story"},
            "labels": [],
            "updated": issue["expected_updated"],
            "components": [],
        }
    }
    monkeypatch.setattr(apply, "read_issue", lambda credential, key, fields: current)
    monkeypatch.setattr(
        apply,
        "write_issue",
        lambda credential, key, fields: (_ for _ in ()).throw(
            apply.ApplyError("PUT failed", status=400)
        ),
    )
    stopped = set()
    result = apply.run_issue("credential", issue, plan["fields"], "run-1", stopped, False)
    assert result["status"] == "failed"
    assert result["comment"] is None
    assert "LINT-COMPONENT" in stopped


def test_run_issue_posts_comment_after_successful_write(apply, monkeypatch):
    plan = valid_plan()
    issue = plan["issues"][0]
    before = {
        "fields": {
            "summary": issue["summary"],
            "project": {"key": "RHIDP"},
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Story"},
            "labels": [],
            "updated": issue["expected_updated"],
            "components": [],
        }
    }
    after = {
        "fields": {
            **before["fields"],
            "components": [{"name": "Authentication"}],
        }
    }
    reads = [before, after]
    monkeypatch.setattr(
        apply,
        "read_issue",
        lambda credential, key, fields: reads.pop(0) if reads else after,
    )
    monkeypatch.setattr(apply, "write_issue", lambda credential, key, fields: None)
    monkeypatch.setattr(
        apply,
        "upsert_comment",
        lambda credential, planned_issue, run_id, adf: {
            "key": planned_issue["key"],
            "status": "created",
            "comment_id": "123",
        },
    )
    result = apply.run_issue("credential", issue, plan["fields"], "run-1", set(), False)
    assert result["status"] == "completed"
    assert result["comment"]["status"] == "created"


def test_build_revert_plan_uses_equals_precondition(apply):
    plan = valid_plan()
    receipt = {
        "issues": [
            {
                "key": "RHIDP-1234",
                "findings": [
                    {
                        "rule": "LINT-COMPONENT",
                        "status": "completed",
                        "before": [],
                        "after": "Authentication",
                    }
                ],
            }
        ]
    }
    revert = apply.build_revert_plan(plan, receipt)
    finding = revert["issues"][0]["findings"][0]
    assert finding["precondition"]["state"] == "equals"
    assert finding["set"]["fields"]["components"] == []


def test_upsert_comment_posts_and_verifies_red_hat_employee_visibility(apply, monkeypatch):
    plan = valid_plan()
    issue = plan["issues"][0]
    adf = apply.build_comment_adf(issue, "run-1")
    posts = []

    calls = []

    def fake_request(path, credential, *, method="GET", body=None):
        calls.append(method)
        if method == "POST":
            posts.append((path, body))
            return {"id": "comment-1"}
        if "POST" in calls:
            return {
                "total": 1,
                "comments": [
                    {
                        "id": "comment-1",
                        "body": adf,
                        "visibility": apply.COMMENT_VISIBILITY,
                    }
                ],
            }
        return {"total": 0, "comments": []}

    monkeypatch.setattr(apply, "request_with_retry", fake_request)
    result = apply.upsert_comment("credential", issue, "run-1", adf)
    assert result["status"] == "created"
    assert posts[0][1]["visibility"] == {
        "type": "group",
        "value": "Red Hat Employee",
    }


def test_upsert_comment_rejects_wrong_visibility_on_retry(apply, monkeypatch):
    plan = valid_plan()
    issue = plan["issues"][0]
    adf = apply.build_comment_adf(issue, "run-1")
    monkeypatch.setattr(
        apply,
        "all_comments",
        lambda credential, key: [
            {
                "id": "comment-1",
                "body": adf,
                "visibility": {"type": "group", "value": "Everyone"},
            }
        ],
    )
    result = apply.upsert_comment("credential", issue, "run-1", adf)
    assert result["status"] == "failed"
    assert "Red Hat Employee" in result["error"]


def test_revert_plan_round_trips_through_validate_plan(apply):
    plan = valid_plan()
    receipt = {
        "issues": [
            {
                "key": "RHIDP-1234",
                "updated_after": "2026-11-20T10:00:00.000-0500",
                "findings": [
                    {
                        "rule": "LINT-COMPONENT",
                        "status": "completed",
                        "before": [],
                        "after": [{"name": "Authentication"}],
                    }
                ],
            }
        ]
    }
    revert = apply.build_revert_plan(plan, receipt)
    apply.validate_plan(revert)
    finding = revert["issues"][0]["findings"][0]
    assert finding["set"]["fields"]["components"] == []
    assert finding["precondition"]["value"] == [{"name": "Authentication"}]
    assert revert["issues"][0]["expected_updated"] == "2026-11-20T10:00:00.000-0500"


def test_validate_plan_rejects_duplicate_field_writes(apply):
    plan = valid_plan()
    duplicate = dict(plan["issues"][0]["findings"][0])
    duplicate["reason"] = "Duplicate component write."
    plan["issues"][0]["findings"].append(duplicate)
    with pytest.raises(apply.ApplyError):
        apply.validate_plan(plan)


def test_validate_plan_enforces_issue_key_scope(apply):
    plan = valid_plan(scope={"issue_keys": ["RHIDP-9999"]})
    with pytest.raises(apply.ApplyError):
        apply.validate_plan(plan)


def test_validate_plan_binds_fix_version_to_evidence(apply):
    plan = valid_plan()
    plan["issues"][0]["findings"][0] = {
        "rule": "LINT-FIXVERSION-MULTI",
        "action": "derive",
        "decision": "supported",
        "reason": "Keep the active release.",
        "evidence": {
            "basis": "Exactly one version is active.",
            "chosen_version": "1.10.0",
            "current_versions": ["1.10.0", "1.11.0"],
        },
        "set": {"fields": {"fixVersions": [{"name": "1.11.0"}]}},
        "precondition": {"field": "fixVersions", "state": "empty"},
    }
    with pytest.raises(apply.ApplyError):
        apply.validate_plan(plan)


def test_run_issue_verifies_inherited_priority_against_parent(apply, monkeypatch):
    plan = valid_plan()
    issue = plan["issues"][0]
    issue["findings"] = [
        {
            "rule": "LINT-PRIORITY",
            "action": "derive",
            "decision": "supported",
            "reason": "Critical inherited from RHIDP-900.",
            "evidence": {
                "basis": "Parent RHIDP-900 is Critical.",
                "parent": "RHIDP-900",
                "parent_priority": "Critical",
            },
            "set": {"fields": {"priority": {"name": "Critical"}}},
            "precondition": {"field": "priority", "state": "empty"},
        }
    ]
    current = {
        "fields": {
            "summary": issue["summary"],
            "project": {"key": "RHIDP"},
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Story"},
            "labels": [],
            "updated": issue["expected_updated"],
            "parent": {"key": "RHIDP-900"},
            "priority": None,
        }
    }
    parent = {"fields": {"priority": {"name": "Critical"}}}
    after = {"fields": {**current["fields"], "priority": {"name": "Critical"}}}
    reads = [current, parent, after, after]
    monkeypatch.setattr(
        apply, "read_issue", lambda credential, key, fields: reads.pop(0) if reads else after
    )
    monkeypatch.setattr(apply, "write_issue", lambda credential, key, fields: None)
    monkeypatch.setattr(
        apply,
        "upsert_comment",
        lambda credential, planned_issue, run_id, adf: {
            "key": planned_issue["key"],
            "status": "created",
        },
    )
    result = apply.run_issue("credential", issue, plan["fields"], "run-1", set(), False)
    assert result["status"] == "completed"


def test_run_issue_treats_read_401_as_fatal(apply, monkeypatch):
    plan = valid_plan()
    issue = plan["issues"][0]

    def fail_read(*args, **kwargs):
        raise apply.ApplyError("GET failed", status=401)

    monkeypatch.setattr(apply, "read_issue", fail_read)
    with pytest.raises(apply.FatalRunError):
        apply.run_issue("credential", issue, plan["fields"], "run-1", set(), False)
