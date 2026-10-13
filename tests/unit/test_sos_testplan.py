"""Unit tests for SoS Test Plan checks."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SOS_SCRIPTS = PROJECT_ROOT / "skills" / "release" / "rhdh-release-sos" / "scripts"

if str(_SOS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SOS_SCRIPTS))

import sos_testplan as testplan_mod  # noqa: E402


class TestTestplanQuery:
    def test_parse_children_assigned(self):
        query = 'testplan children assigned summary ~ "Test Plan"'
        assert testplan_mod.is_testplan_query(query)
        kind, pattern, extra = testplan_mod.parse_testplan_query(query)
        assert kind == "children assigned"
        assert pattern == "Test Plan"
        assert extra is None

    def test_parse_signoff_open(self):
        query = 'testplan signoff open summary ~ "Test Plan"'
        kind, pattern, extra = testplan_mod.parse_testplan_query(query)
        assert kind == "signoff open"
        assert pattern == "Test Plan"
        assert extra is None

    def test_end_milestone_is_feature_freeze(self):
        query = 'testplan signoff open summary ~ "Test Plan"'
        assert testplan_mod.testplan_end_milestone_key(query) == "feature_freeze"


class TestTestplanEvaluation:
    def test_children_all_assigned(self):
        result = testplan_mod.evaluate_children_assigned(
            [{"key": "RHIDP-1", "assignee": "Alex"}, {"key": "RHIDP-2", "assignee": "Bob"}]
        )
        assert result["state"] == "ok"
        assert result["summary"] == "All assigned (2 tasks)"

    def test_children_unassigned(self):
        result = testplan_mod.evaluate_children_assigned(
            [{"key": "RHIDP-1", "assignee": ""}, {"key": "RHIDP-2", "assignee": "Bob"}]
        )
        assert result["state"] == "action_needed"
        assert result["summary"] == "1 unassigned task"
        assert result["unassigned_count"] == 1

    def test_signoff_all_closed(self):
        result = testplan_mod.evaluate_signoff_open(
            [
                {"key": "RHIDP-10", "summary": "QE sign-off", "status": "Closed"},
                {"key": "RHIDP-11", "summary": "Docs sign-off", "status": "Closed"},
            ]
        )
        assert result["state"] == "ok"
        assert result["summary"] == "Signed off (2 tasks)"
        assert result["issues"] == []

    def test_signoff_open_tasks(self):
        result = testplan_mod.evaluate_signoff_open(
            [
                {"key": "RHIDP-10", "summary": "QE sign-off", "status": "In Progress"},
                {"key": "RHIDP-11", "summary": "Docs sign-off", "status": "Closed"},
            ]
        )
        assert result["state"] == "action_needed"
        assert result["summary"] == "1 sign-off task open"
        assert result["issues"][0]["key"] == "RHIDP-10"


class TestTestplanJql:
    def test_build_epic_jql(self):
        jql_mod = MagicMock()
        jql_mod.compose_fragment.return_value = "epic jql"
        jql = testplan_mod.build_testplan_epic_jql("Test Plan", "2.1.0", jql_mod)
        assert jql == "epic jql"
        jql_mod.compose_fragment.assert_called_once_with(
            'summary ~ "Test Plan"',
            version="2.1.0",
            extra="issuetype = Epic AND status != closed",
        )

    def test_children_jql(self):
        assert "parent = RHIDP-1" in testplan_mod.children_jql("RHIDP-1")
        assert "issuetype in (Task, Sub-task)" in testplan_mod.children_jql("RHIDP-1")
