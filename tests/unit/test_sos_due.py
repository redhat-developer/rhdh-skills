"""Unit tests for SoS due static checks."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SOS_SCRIPTS = PROJECT_ROOT / "skills" / "release" / "rhdh-release-sos" / "scripts"

if str(_SOS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SOS_SCRIPTS))

import sos_due as due_mod  # noqa: E402


class TestDueStaticQuery:
    def test_detects_due_static_query(self):
        query = 'due static "Feature Freeze"'
        assert due_mod.is_due_static_query(query)
        assert due_mod.due_static_filter_name(query) == "Feature Freeze"
        assert due_mod.due_static_milestone_key(query) == "feature_freeze"

    def test_code_freeze_due_static_query(self):
        query = 'due static "Code Freeze"'
        assert due_mod.is_due_static_query(query)
        assert due_mod.due_static_filter_name(query) == "Code Freeze"
        assert due_mod.due_static_milestone_key(query) == "code_freeze"

    def test_check_end_milestone_key(self):
        assert due_mod.check_end_milestone_key('due static "Feature Freeze"') == "feature_freeze"
        assert due_mod.check_end_milestone_key('due static "Code Freeze"') == "code_freeze"
        assert (
            due_mod.check_end_milestone_key('metric epic_dev_complete static "Feature Freeze"')
            == "feature_freeze"
        )
        assert due_mod.check_end_milestone_key('static "Feature Freeze"') is None

    def test_ends_at_feature_freeze(self):
        assert due_mod.ends_at_feature_freeze('due static "Feature Freeze"')
        assert due_mod.ends_at_feature_freeze('metric epic_dev_complete static "Feature Freeze"')
        assert not due_mod.ends_at_feature_freeze('due static "Code Freeze"')
        assert not due_mod.ends_at_feature_freeze('static "Feature Freeze"')

    def test_ends_at_feature_freeze_legacy_list_query(self):
        assert not due_mod.is_due_static_query('list static "Feature Freeze"')
