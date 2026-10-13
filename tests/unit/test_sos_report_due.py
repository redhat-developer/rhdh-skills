"""Unit tests for epic dev complete due-window filtering."""

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SOS_SCRIPTS = PROJECT_ROOT / "skills" / "release" / "rhdh-release-sos" / "scripts"

if str(_SOS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SOS_SCRIPTS))

import sos_checks as checks_mod  # noqa: E402
import sos_report as report_mod  # noqa: E402

METRIC_ROW = checks_mod.CheckRow(
    section=checks_mod.SectionHeader(title="Feature Freeze", milestone_key="feature_freeze"),
    when_raw="FF - 21d",
    title="FF Epics Dev Complete",
    query='metric epic_dev_complete static "Feature Freeze"',
    resolved_date=date(2026, 9, 1),
)

DUE_ROW = checks_mod.CheckRow(
    section=checks_mod.SectionHeader(title="Feature Freeze", milestone_key="feature_freeze"),
    when_raw="FF - 21d",
    title="FF work remaining for Feature Freeze",
    query='due static "Feature Freeze"',
    resolved_date=date(2026, 9, 1),
)

CF_DUE_ROW = checks_mod.CheckRow(
    section=checks_mod.SectionHeader(title="Code Freeze", milestone_key="code_freeze"),
    when_raw="CF - 14d",
    title="CF work remaining for Code Freeze",
    query='due static "Code Freeze"',
    resolved_date=date(2026, 9, 29),
)

COUNT_ROW = checks_mod.CheckRow(
    section=checks_mod.SectionHeader(title="Feature Freeze", milestone_key="feature_freeze"),
    when_raw="FF - 21d",
    title="FF scope not in sprint",
    query='static "Feature Freeze" + sprint is EMPTY',
    resolved_date=date(2026, 9, 1),
)

MILESTONES = {
    "feature_freeze": "2026-09-22",
    "code_freeze": "2026-10-13",
    "go_no_go": "2026-10-26",
    "ga_announce": "2026-10-28",
}


class TestFilterDueChecks:
    def test_keeps_metric_check_on_feature_freeze_day(self):
        due = report_mod._filter_due_checks(
            [METRIC_ROW, COUNT_ROW],
            as_of=date(2026, 9, 22),
            milestones=MILESTONES,
        )
        assert [row.title for row in due] == [
            "FF Epics Dev Complete",
            "FF scope not in sprint",
        ]

    def test_drops_metric_check_after_feature_freeze_day(self):
        due = report_mod._filter_due_checks(
            [METRIC_ROW, COUNT_ROW],
            as_of=date(2026, 9, 23),
            milestones=MILESTONES,
        )
        assert [row.title for row in due] == ["FF scope not in sprint"]

    def test_drops_due_static_check_after_feature_freeze_day(self):
        due = report_mod._filter_due_checks(
            [DUE_ROW, COUNT_ROW],
            as_of=date(2026, 9, 23),
            milestones=MILESTONES,
        )
        assert [row.title for row in due] == ["FF scope not in sprint"]

    def test_keeps_code_freeze_due_static_on_code_freeze_day(self):
        due = report_mod._filter_due_checks(
            [CF_DUE_ROW],
            as_of=date(2026, 10, 13),
            milestones=MILESTONES,
        )
        assert [row.title for row in due] == ["CF work remaining for Code Freeze"]

    def test_drops_code_freeze_due_static_after_code_freeze_day(self):
        due = report_mod._filter_due_checks(
            [CF_DUE_ROW],
            as_of=date(2026, 10, 14),
            milestones=MILESTONES,
        )
        assert due == []
