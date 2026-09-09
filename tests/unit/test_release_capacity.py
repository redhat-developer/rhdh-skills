"""Behavior tests for release-horizon capacity arithmetic."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from io import StringIO
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    PROJECT_ROOT / "skills" / "release" / "rhdh-release-capacity-plan" / "scripts" / "capacity.py"
)
SPEC = importlib.util.spec_from_file_location("release_capacity", SCRIPT)
assert SPEC
assert SPEC.loader
CAPACITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPACITY)


def _issue(key: str, points: float | None, status: str, added: bool) -> dict:
    return {
        "key": key,
        "story_points": points,
        "status": status,
        "added_after_start": added,
    }


def _members(*names: str, availability: float = 1.0) -> list[dict]:
    return [{"name": name, "availability": availability} for name in names]


def _sample_issues() -> list[dict]:
    return [
        _issue("RHIDP-1", 8, "Closed", False),
        _issue("RHIDP-2", 7, "Release Pending", False),
        _issue("RHIDP-3", 5, "Closed", True),
        _issue("RHIDP-4", 3, "To Do", True),
    ]


def _sprint(name: str = "RHDH COPE 3289", **overrides) -> dict:
    sprint = {
        "id": 47486,
        "name": name,
        "burndown_url": (
            "https://redhat.atlassian.net/jira/software/c/projects/RHIDP/"
            "boards/11374/reports/burndown-chart?sprint=47486"
        ),
        "issues": _sample_issues(),
    }
    sprint.update(overrides)
    return sprint


def _snapshot(**overrides) -> dict:
    payload = {
        "team": "RHDH Cope",
        "version": "2.2",
        "board_id": 11374,
        "meeting_factor": 0.4,
        "remaining_sprints": 4,
        "feature_freeze": "2026-10-01",
        "code_freeze": "2026-11-01",
        "members": _members("Ada", "Bea"),
        "sprints": [_sprint(), _sprint(name="RHDH COPE 3288", id=47424)],
        "features": [],
    }
    payload.update(overrides)
    return payload


def test_reconstructed_issues_split_interrupt_from_planned():
    metrics = CAPACITY.sprint_from_issues(_sample_issues())

    assert metrics["completed_sp"] == 20
    assert metrics["interrupt_sp"] == 8
    assert metrics["planned_completed_sp"] == 15
    assert metrics["completed_count"] == 3
    assert metrics["interrupt_count"] == 2
    assert metrics["planned_completed_count"] == 2
    assert metrics["interrupt_rate"] == pytest.approx(8 / 20)


def test_greenhopper_sprintreport_uses_added_during_sprint_keys():
    report = {
        "rapidViewId": 11374,
        "sprint": {"id": 47486, "name": "RHDH COPE 3289", "state": "CLOSED"},
        "contents": {
            "completedIssues": [
                {
                    "key": "RHIDP-1",
                    "statusName": "Closed",
                    "currentEstimate": 8,
                },
                {
                    "key": "RHIDP-3",
                    "statusName": "Closed",
                    "estimateStatistic": {
                        "statFieldId": "customfield_10028",
                        "statFieldValue": {"value": 5.0, "text": "5"},
                    },
                },
            ],
            "issuesNotCompletedInCurrentSprint": [
                {"key": "RHIDP-4", "statusName": "To Do", "currentEstimate": 3}
            ],
            "issueKeysAddedDuringSprint": {"RHIDP-3": True, "RHIDP-4": True},
            "completedIssuesEstimateSum": {"value": 13, "text": "13.0"},
        },
    }

    metrics = CAPACITY.sprint_from_greenhopper(report)

    assert metrics["completed_sp"] == 13
    assert metrics["interrupt_sp"] == 8
    assert metrics["planned_completed_sp"] == 8
    assert metrics["interrupt_count"] == 2


def test_greenhopper_reads_current_estimate_statistic():
    report = {
        "contents": {
            "completedIssues": [
                {
                    "key": "RHIDP-1",
                    "statusName": "Closed",
                    "currentEstimateStatistic": {
                        "statFieldId": "customfield_10028",
                        "statFieldValue": {"value": 8.0},
                    },
                }
            ],
            "issueKeysAddedDuringSprint": {},
        }
    }
    metrics = CAPACITY.sprint_from_greenhopper(report)
    assert metrics["completed_sp"] == 8
    assert metrics["planned_completed_sp"] == 8


def test_greenhopper_snapshot_feeds_the_same_ledgers_as_issues():
    report = {
        "contents": {
            "completedIssues": [
                {"key": "RHIDP-1", "statusName": "Closed", "currentEstimate": 8},
                {
                    "key": "RHIDP-2",
                    "statusName": "Release Pending",
                    "currentEstimate": 7,
                },
                {"key": "RHIDP-3", "statusName": "Closed", "currentEstimate": 5},
            ],
            "issuesNotCompletedInCurrentSprint": [
                {"key": "RHIDP-4", "statusName": "To Do", "currentEstimate": 3}
            ],
            "issueKeysAddedDuringSprint": {"RHIDP-3": True, "RHIDP-4": True},
        }
    }
    from_gh = CAPACITY.compute(
        _snapshot(
            sprints=[
                _sprint(greenhopper_sprintreport=report, issues=None),
                _sprint(
                    name="RHDH COPE 3288",
                    id=47424,
                    greenhopper_sprintreport=report,
                    issues=None,
                ),
            ]
        )
    )
    from_issues = CAPACITY.compute(_snapshot())

    assert from_gh["ledgers"]["historical"]["net"] == from_issues["ledgers"]["historical"]["net"]
    assert from_gh["sprints"][0]["source"] == "greenhopper"


def test_both_ledgers_and_inferred_rate_is_not_double_counted():
    result = CAPACITY.compute(_snapshot())
    historical = result["ledgers"]["historical"]
    theoretical = result["ledgers"]["theoretical"]

    assert historical["mean_planned_completed"] == 15
    assert historical["net"] == 60
    assert historical["arithmetic"] == "15 × 4 × 1 = 60"

    assert theoretical["sp_per_person_sprint_source"] == "inferred_backed_out"
    assert theoretical["interrupt_rate"] == pytest.approx(0.4)
    assert theoretical["net"] == pytest.approx(80)
    assert "0.6" in theoretical["arithmetic"]
    assert result["unit"] == "sp"
    assert result["interrupt_retrieved"] is True
    assert result["ledgers"]["fillable"]["net"] == 60
    assert result["ledgers"]["fillable"]["is_upper_bound"] is False
    assert result["ledgers"]["interrupt_reserve"]["net"] == pytest.approx(32)
    assert result["fit"]["required_vs_fillable"]["capacity"] == 60
    assert result["fit"]["fill_against"] == "fillable"


def test_user_full_focus_rate_is_used_raw():
    result = CAPACITY.compute(_snapshot(sp_per_person_sprint=10))
    theoretical = result["ledgers"]["theoretical"]

    assert theoretical["sp_per_person_sprint_source"] == "user_full_focus"
    assert theoretical["sp_per_person_sprint"] == 10
    assert theoretical["net"] == pytest.approx(28.8)


def test_meeting_factor_override_changes_theoretical_only():
    defaulted = CAPACITY.compute(_snapshot())
    overridden = CAPACITY.compute(_snapshot(meeting_factor=0.2, sp_per_person_sprint=10))

    assert defaulted["ledgers"]["historical"]["net"] == overridden["ledgers"]["historical"]["net"]
    assert overridden["meeting_factor"] == 0.2
    assert overridden["ledgers"]["theoretical"]["net"] == pytest.approx(2 * 4 * 10 * 0.8 * 0.6)


def test_feature_tshirt_uses_placeholder_fibonacci_not_velocity():
    result = CAPACITY.compute(
        _snapshot(
            features=[
                {
                    "key": "RHDHPLAN-100",
                    "summary": "Catalog search",
                    "size": "M",
                    "stretch": False,
                    "epics": [],
                }
            ]
        )
    )

    item = result["demand"]["items"][0]
    assert item["basis"] == "feature_tshirt"
    assert item["sp"] == 8
    assert item["tshirt_placeholder"] is True
    assert result["demand"]["required_sp"] == 8
    assert result["demand"]["tshirt_placeholder"] is True
    assert "placeholder" in result["demand"]["tshirt_placeholder_note"]
    assert result["demand"]["tshirt_placeholder_sp"]["XS"] == 3
    assert result["fit"]["required_vs_historical"]["fits"] is True


def test_epic_child_story_points_win_over_tshirt():
    result = CAPACITY.compute(
        _snapshot(
            features=[
                {
                    "key": "RHDHPLAN-200",
                    "summary": "Auth",
                    "size": "XL",
                    "epics": [
                        {
                            "key": "RHIDP-5000",
                            "summary": "OIDC",
                            "size": "L",
                            "story_points": 13,
                        }
                    ],
                }
            ]
        )
    )

    item = result["demand"]["items"][0]
    assert item["basis"] == "epics"
    assert item["sp"] == 13
    assert item["tshirt_placeholder"] is False
    assert result["demand"]["unsized"] == []
    assert result["demand"]["tshirt_placeholder"] is False
    assert result["demand"]["tshirt_placeholder_note"] is None


def test_epic_tshirt_fallback_when_children_have_no_points():
    result = CAPACITY.compute(
        _snapshot(
            features=[
                {
                    "key": "RHDHPLAN-201",
                    "size": "L",
                    "epics": [{"key": "RHIDP-5001", "size": "S", "story_points": None}],
                }
            ]
        )
    )

    item = result["demand"]["items"][0]
    assert item["sp"] == 5
    assert item["tshirt_placeholder"] is True
    assert result["demand"]["tshirt_placeholder"] is True


def test_unsized_features_are_flagged_not_invented():
    result = CAPACITY.compute(
        _snapshot(
            features=[
                {"key": "RHDHPLAN-300", "summary": "Unknown", "epics": []},
                {
                    "key": "RHDHPLAN-301",
                    "epics": [{"key": "RHIDP-9", "story_points": None}],
                },
            ]
        )
    )

    assert result["demand"]["total_sp"] == 0
    assert result["demand"]["unsized"] == ["RHDHPLAN-300", "RHIDP-9"]
    assert result["demand"]["tshirt_placeholder"] is False
    assert result["demand"]["tshirt_placeholder_note"] is None


def test_stretch_features_are_first_cuts_and_excluded_from_required():
    result = CAPACITY.compute(
        _snapshot(
            features=[
                {"key": "RHDHPLAN-10", "size": "XS", "stretch": False, "epics": []},
                {"key": "RHDHPLAN-11", "size": "S", "stretch": True, "epics": []},
            ]
        )
    )

    assert result["stretch_first_cuts"] == ["RHDHPLAN-11"]
    assert result["demand"]["required_sp"] == 3
    assert result["demand"]["stretch_sp"] == 5
    assert result["demand"]["total_sp"] == 8
    assert result["demand"]["items"][0]["tshirt_placeholder"] is True


def test_low_story_point_coverage_falls_back_to_issue_counts():
    thin = [
        _issue("RHIDP-1", 5, "Closed", False),
        _issue("RHIDP-2", None, "Closed", False),
        _issue("RHIDP-3", None, "Closed", True),
    ]
    result = CAPACITY.compute(
        _snapshot(sprints=[_sprint(issues=thin), _sprint(name="RHDH COPE 3288", issues=thin)])
    )

    assert result["coverage"] == pytest.approx(1 / 3)
    assert result["coverage_warning"] is True
    assert result["unit"] == "issues"
    assert result["ledgers"]["historical"]["mean_planned_completed"] == 2


def test_remaining_sprints_from_code_freeze():
    assert CAPACITY.remaining_sprints(date(2026, 9, 3), date(2026, 11, 1)) == 3
    assert CAPACITY.remaining_sprints(date(2026, 11, 1), date(2026, 11, 1)) == 0
    assert CAPACITY.remaining_sprints(date(2026, 9, 3), date(2026, 11, 1), sprint_days=14) == 5

    result = CAPACITY.compute(
        _snapshot(
            remaining_sprints=None,
            today="2026-09-03",
            code_freeze="2026-11-01",
        )
    )
    assert result["remaining_sprints"] == 3
    assert result["sprint_days"] == 21
    assert result["ledgers"]["historical"]["net"] == 45


def test_snapshot_sprint_days_overrides_default_horizon():
    result = CAPACITY.compute(
        _snapshot(
            remaining_sprints=None,
            today="2026-09-03",
            code_freeze="2026-11-01",
            sprint_days=14,
        )
    )
    assert result["remaining_sprints"] == 5
    assert result["sprint_days"] == 14
    assert result["ledgers"]["historical"]["net"] == 75


def test_availability_scales_historical_ledger():
    result = CAPACITY.compute(
        _snapshot(
            members=[
                {"name": "Ada", "availability": 1.0},
                {"name": "Bea", "availability": 0.5},
            ]
        )
    )

    assert result["available_people"] == 1.5
    assert result["availability_factor"] == pytest.approx(0.75)
    assert result["ledgers"]["historical"]["net"] == pytest.approx(45)


def test_cli_help_and_json_round_trip(capsys, tmp_path):
    with pytest.raises(SystemExit) as help_exit:
        CAPACITY.main(["--help"])
    assert help_exit.value.code == 0
    assert "--input" in capsys.readouterr().out

    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps(_snapshot()), encoding="utf-8")
    assert CAPACITY.main(["--input", str(snapshot)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["ledgers"]["historical"]["net"] == 60


def test_cli_rejects_empty_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", StringIO(""))
    monkeypatch.setattr(CAPACITY.sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit) as exited:
        CAPACITY.main([])
    assert exited.value.code == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_cli_rejects_bad_meeting_factor(capsys, tmp_path):
    snapshot = tmp_path / "bad.json"
    snapshot.write_text(json.dumps(_snapshot(meeting_factor=1.0)), encoding="utf-8")
    with pytest.raises(SystemExit) as exited:
        CAPACITY.main(["--input", str(snapshot)])
    assert exited.value.code == 1
    assert "meeting_factor" in json.loads(capsys.readouterr().out)["error"]


def test_availability_from_pto_clips_and_uses_weekdays():
    # 7 remaining 21-day sprints → 7 × 15 weekdays = 105
    assert CAPACITY.weekday_count(21) == 15
    assert CAPACITY.availability_from_pto(0, 7) == 1.0
    assert CAPACITY.availability_from_pto(10.5, 7) == pytest.approx(0.9)
    assert CAPACITY.availability_from_pto(200, 7) == 0.0
    assert CAPACITY.count_weekdays(date(2026, 9, 7), date(2026, 9, 12)) == 5
    assert CAPACITY.count_weekdays(date(2026, 9, 12), date(2026, 9, 14)) == 0


def test_unretrieved_interrupt_is_upper_bound_not_zero_rate():
    closed_only = [
        _issue("RHIDP-1", 8, "Closed", False),
        _issue("RHIDP-2", 7, "Closed", False),
    ]
    result = CAPACITY.compute(
        _snapshot(
            interrupt_retrieved=False,
            sprints=[
                _sprint(issues=closed_only),
                _sprint(name="RHDH COPE 3288", id=47424, issues=closed_only),
            ],
        )
    )

    assert result["interrupt_retrieved"] is False
    assert result["interrupt_rate"] is None
    assert result["ledgers"]["fillable"]["is_upper_bound"] is True
    assert result["ledgers"]["interrupt_reserve"] is None
    assert result["ledgers"]["theoretical"]["interrupt_applied"] is False
    assert result["ledgers"]["theoretical"]["interrupt_rate"] is None
    assert result["ledgers"]["theoretical"]["arithmetic"] == "2 × 4 × 12.5 × 0.6 = 60"
    assert result["ledgers"]["fillable"]["net"] == result["ledgers"]["historical"]["net"]


def test_inferred_unretrieved_when_no_added_after_start_and_not_greenhopper():
    issues = [
        {"key": "RHIDP-1", "story_points": 8, "status": "Closed"},
        {"key": "RHIDP-2", "story_points": 7, "status": "Closed"},
    ]
    result = CAPACITY.compute(
        _snapshot(sprints=[_sprint(issues=issues), _sprint(name="B", id=2, issues=issues)])
    )
    assert result["interrupt_retrieved"] is False
    assert result["ledgers"]["fillable"]["is_upper_bound"] is True


def test_all_false_added_after_start_is_unretrieved_unless_snapshot_says_otherwise():
    issues = [
        _issue("RHIDP-1", 8, "Closed", False),
        _issue("RHIDP-2", 7, "Closed", False),
    ]
    inferred = CAPACITY.compute(
        _snapshot(sprints=[_sprint(issues=issues), _sprint(name="B", id=2, issues=issues)])
    )
    asserted = CAPACITY.compute(
        _snapshot(
            interrupt_retrieved=True,
            sprints=[_sprint(issues=issues), _sprint(name="B", id=2, issues=issues)],
        )
    )
    assert inferred["interrupt_retrieved"] is False
    assert inferred["interrupt_rate"] is None
    assert asserted["interrupt_retrieved"] is True
    assert asserted["interrupt_rate"] == 0.0
    assert asserted["ledgers"]["interrupt_reserve"]["net"] == 0


def test_greenhopper_rolled_forward_is_not_completed_this_sprint():
    report = {
        "contents": {
            "completedIssues": [{"key": "RHIDP-1", "statusName": "Closed", "currentEstimate": 8}],
            "issuesCompletedInAnotherSprint": [
                {"key": "RHIDP-9", "statusName": "Closed", "currentEstimate": 13}
            ],
            "issueKeysAddedDuringSprint": {"RHIDP-4": True},
            "issuesNotCompletedInCurrentSprint": [
                {"key": "RHIDP-4", "statusName": "To Do", "currentEstimate": 3}
            ],
            "completedIssuesEstimateSum": {"value": 8, "text": "8.0"},
            "completedIssuesInitialEstimateSum": {"value": 8, "text": "8.0"},
            "issuesNotCompletedInitialEstimateSum": {"value": 5, "text": "5.0"},
        }
    }

    metrics = CAPACITY.sprint_from_greenhopper(report)

    assert metrics["completed_sp"] == 8
    assert metrics["planned_completed_sp"] == 8
    assert metrics["interrupt_sp"] == 3
    assert metrics["committed_sp"] == 13
    assert metrics["completed_count"] == 1
