"""Unit tests for SoS expect checks."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SOS_SCRIPTS = PROJECT_ROOT / "skills" / "release" / "rhdh-release-sos" / "scripts"

if str(_SOS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SOS_SCRIPTS))

import sos_expect as expect_mod  # noqa: E402


class TestExpectAssigneeQuery:
    def test_detects_expect_assignee_query(self):
        query = 'expect assignee summary ~ "Test Day"'
        assert expect_mod.is_expect_query(query)
        assert expect_mod.is_expect_assignee_query(query)
        assert expect_mod.expect_assignee_summary_pattern(query) == "Test Day"

    def test_rejects_other_expect_forms(self):
        assert not expect_mod.is_expect_assignee_query('expect status summary ~ "Foo"')
        assert not expect_mod.is_expect_assignee_query('due static "Feature Freeze"')

    def test_parse_expect_assignee_with_extra_jql(self):
        query = 'expect assignee summary ~ "Test Day" + issuetype = Epic'
        assert expect_mod.is_expect_assignee_query(query)
        pattern, extra = expect_mod.parse_expect_assignee_query(query)
        assert pattern == "Test Day"
        assert extra == "issuetype = Epic"

    def test_build_expect_assignee_jql(self):
        jql_mod = MagicMock()
        jql_mod.compose_fragment.return_value = "composed jql"
        jql = expect_mod.build_expect_assignee_jql(
            "Test Day",
            "2.1.0",
            jql_mod,
            extra="issuetype = Epic",
        )
        assert jql == "composed jql"
        jql_mod.compose_fragment.assert_called_once_with(
            'summary ~ "Test Day"',
            version="2.1.0",
            extra="status != closed AND issuetype = Epic",
        )

    def test_build_expect_assignee_jql_without_extra(self):
        jql_mod = MagicMock()
        jql_mod.compose_fragment.return_value = "composed jql"
        expect_mod.build_expect_assignee_jql("Test Day", "2.1.0", jql_mod)
        jql_mod.compose_fragment.assert_called_once_with(
            'summary ~ "Test Day"',
            version="2.1.0",
            extra="status != closed",
        )


class TestEvaluateExpectAssignee:
    def test_not_found(self):
        result = expect_mod.evaluate_expect_assignee([])
        assert result["expect_state"] == "not_found"
        assert "Not found" in result["summary"]

    def test_ambiguous(self):
        result = expect_mod.evaluate_expect_assignee([{"key": "RHIDP-1"}, {"key": "RHIDP-2"}])
        assert result["expect_state"] == "ambiguous"
        assert "Multiple matches" in result["summary"]

    def test_unassigned(self):
        result = expect_mod.evaluate_expect_assignee([{"key": "RHIDP-9", "assignee": ""}])
        assert result["expect_state"] == "unassigned"
        assert result["issue_key"] == "RHIDP-9"
        assert "Unassigned" in result["summary"]

    def test_assigned(self):
        result = expect_mod.evaluate_expect_assignee([{"key": "RHIDP-9", "assignee": "Jane Doe"}])
        assert result["expect_state"] == "assigned"
        assert result["summary"] == "Assigned (RHIDP-9)"
        assert result["assignee"] == "Jane Doe"
        assert result["issue_url"].endswith("/browse/RHIDP-9")
