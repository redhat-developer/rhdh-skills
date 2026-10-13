"""Unit tests for the SoS check runbook parser and timeline selection."""

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SOS_SCRIPTS = PROJECT_ROOT / "skills" / "release" / "rhdh-release-sos" / "scripts"

if str(_SOS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SOS_SCRIPTS))

import sos_checks as checks_mod  # noqa: E402

SAMPLE_TABLE = """
| When | Check | Query | Action item |
|------|-------|-------|-------------|
| Feature Freeze | | | |
| FF - 21d | FF scope not in sprint | static "Feature Freeze" + sprint is EMPTY | Plan every FF Story and Task into the current or next sprint. |
| FF - 7d | FF scope still in New | static "Feature Freeze" + status = New | Move FF scope out of New into active work. |
| Code Freeze | | | |
| CF - 7d | Blocker bugs | template blockers | Resolve or downgrade every open blocker before Code Freeze. |
"""

MILESTONES = {
    "feature_freeze": "2026-09-22",
    "code_freeze": "2026-10-13",
    "go_no_go": "2026-10-26",
    "ga_announce": "2026-10-28",
}


class TestParseChecks:
    def test_parses_section_headers_and_checks(self):
        rows = checks_mod.parse_checks(SAMPLE_TABLE)
        assert len(rows) == 5
        assert rows[0].title == "Feature Freeze"
        assert rows[1].title == "FF scope not in sprint"
        assert rows[1].action_item == (
            "Plan every FF Story and Task into the current or next sprint."
        )
        assert rows[3].title == "Code Freeze"


class TestResolveWhen:
    def test_relative_to_feature_freeze(self):
        resolved = checks_mod.resolve_when("FF - 21d", MILESTONES)
        assert resolved == date(2026, 9, 1)

    def test_absolute_date(self):
        resolved = checks_mod.resolve_when("2026-09-08", MILESTONES)
        assert resolved == date(2026, 9, 8)


class TestCurrentSection:
    def test_before_feature_freeze(self):
        assert checks_mod.current_section_key(date(2026, 9, 2), MILESTONES) == "feature_freeze"

    def test_between_feature_and_code_freeze(self):
        assert checks_mod.current_section_key(date(2026, 9, 25), MILESTONES) == "code_freeze"


class TestSelectChecks:
    def test_cumulative_due_and_upcoming_in_active_section(self):
        rows = checks_mod.attach_dates(checks_mod.parse_checks(SAMPLE_TABLE), MILESTONES)
        due, upcoming, section = checks_mod.select_checks(
            rows, as_of=date(2026, 9, 2), milestones=MILESTONES
        )
        assert section.milestone_key == "feature_freeze"
        assert [row.title for row in due] == ["FF scope not in sprint"]
        assert [row.title for row in upcoming] == ["FF scope still in New"]

    def test_code_freeze_section_excludes_feature_freeze_checks(self):
        rows = checks_mod.attach_dates(checks_mod.parse_checks(SAMPLE_TABLE), MILESTONES)
        due, upcoming, section = checks_mod.select_checks(
            rows, as_of=date(2026, 9, 25), milestones=MILESTONES
        )
        assert section.milestone_key == "code_freeze"
        assert due == []
        assert [row.title for row in upcoming] == ["Blocker bugs"]

    def test_test_day_expect_check_due_during_feature_freeze_section(self):
        rows = checks_mod.attach_dates(checks_mod.load_checks(), MILESTONES)
        due, _upcoming, section = checks_mod.select_checks(
            rows, as_of=date(2026, 9, 4), milestones=MILESTONES
        )
        assert section.milestone_key == "feature_freeze"
        assert "Test Day ticket has owner" in [row.title for row in due]

    def test_unassigned_stories_tasks_check_due_at_ff_minus_21d(self):
        rows = checks_mod.attach_dates(checks_mod.load_checks(), MILESTONES)
        due, _upcoming, section = checks_mod.select_checks(
            rows, as_of=date(2026, 9, 1), milestones=MILESTONES
        )
        assert section.milestone_key == "feature_freeze"
        row = next(row for row in due if row.title == "FF Stories, Tasks unassigned")
        assert row.when_raw == "FF - 21d"
        assert row.resolved_date == date(2026, 9, 1)
        assert (
            row.query
            == 'static "Feature Freeze" + assignee is EMPTY AND issuetype in (Story, Task)'
        )
        assert row.action_item == "Assign an owner to every unassigned FF Story and Task."

    def test_snapshot_checks_may_leave_action_item_blank(self):
        rows = checks_mod.load_checks()
        ff_snapshot = next(
            row
            for row in rows
            if isinstance(row, checks_mod.CheckRow) and row.title == "Feature Freeze day snapshot"
        )
        cf_snapshot = next(
            row
            for row in rows
            if isinstance(row, checks_mod.CheckRow) and row.title == "Code Freeze day snapshot"
        )
        assert ff_snapshot.action_item == ""
        assert cf_snapshot.action_item == ""
