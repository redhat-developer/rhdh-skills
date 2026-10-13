"""Unit tests for SoS metric checks."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SOS_SCRIPTS = PROJECT_ROOT / "skills" / "release" / "rhdh-release-sos" / "scripts"
_STATUS_SCRIPTS = PROJECT_ROOT / "skills" / "release" / "rhdh-release-status" / "scripts"

for path in (_SOS_SCRIPTS, _STATUS_SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import jql as jql_mod  # noqa: E402
import rich_filter as rf_mod  # noqa: E402
import sos_metrics as metrics_mod  # noqa: E402

FF_FRAGMENT = (
    "resolution is EMPTY AND component not in (AI) AND Type not in (Bug, sub-task) "
    'AND status not in ("Dev Complete", Done) AND (labels is EMPTY OR labels != stretch-goal)'
)


class TestEpicDevCompleteMetric:
    def test_query_detection(self):
        query = 'metric epic_dev_complete static "Feature Freeze"'
        assert metrics_mod.is_epic_dev_complete_query(query)
        assert metrics_mod.epic_dev_complete_filter_name(query) == "Feature Freeze"

    def test_strip_status_exclusion(self):
        stripped = metrics_mod.strip_status_exclusion(FF_FRAGMENT)
        assert "status not in" not in stripped
        assert "component not in" in stripped

    def test_build_jql(self, tmp_path, monkeypatch):
        rf_path = tmp_path / "rf.json"
        rf_path.write_text(
            json.dumps(
                {
                    "richFilter": {
                        "jiraFilter": {"jql": "project = RHIDP"},
                        "staticFilters": [{"name": "Feature Freeze", "jql": FF_FRAGMENT}],
                    }
                }
            )
        )
        monkeypatch.setattr(rf_mod, "discover", lambda: rf_path)
        jql_mod.set_rich_filter_path(rf_path)
        rf_mod.reset_cache()

        all_jql = metrics_mod.build_epic_dev_complete_jql(
            "Feature Freeze", "2.1.0", jql_mod, rf_mod, dev_complete_only=False
        )
        complete_jql = metrics_mod.build_epic_dev_complete_jql(
            "Feature Freeze", "2.1.0", jql_mod, rf_mod, dev_complete_only=True
        )

        assert 'fixVersion = "2.1.0"' in all_jql
        assert "issuetype = Epic" in all_jql
        assert "status not in" not in all_jql
        assert 'status = "Dev Complete"' in complete_jql

    def test_ratio_summary(self):
        assert metrics_mod.ratio_summary(12, 18, status="ok") == "67% (12/18)"
        assert metrics_mod.ratio_summary(0, 0, status="ok") == "None"
        assert metrics_mod.ratio_summary(None, None, status="unverified") == "Unverified"

    def test_ratio_percent_rounds(self):
        assert metrics_mod.ratio_percent(1, 3) == 33
        assert metrics_mod.ratio_percent(2, 2) == 100
