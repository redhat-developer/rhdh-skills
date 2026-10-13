"""Due-by-milestone checks for SoS reports (`due static "Name"`)."""

from __future__ import annotations

import re

_DUE_STATIC = re.compile(r'^due\s+static\s+"([^"]+)"$', re.IGNORECASE)
_DUE_STATIC_MILESTONES = {
    "Feature Freeze": "feature_freeze",
    "Code Freeze": "code_freeze",
}


def is_due_static_query(query: str) -> bool:
    return _DUE_STATIC.match(query.strip()) is not None


def due_static_filter_name(query: str) -> str:
    match = _DUE_STATIC.match(query.strip())
    if not match:
        raise ValueError(f"Not a due static query: {query!r}")
    return match.group(1)


def due_static_milestone_key(query: str) -> str | None:
    """Milestone calendar key for a due static query, if supported."""
    if not is_due_static_query(query):
        return None
    return _DUE_STATIC_MILESTONES.get(due_static_filter_name(query))


def check_end_milestone_key(query: str) -> str | None:
    """Milestone after which this check must not run."""
    from sos_metrics import is_epic_dev_complete_query
    from sos_testplan import testplan_end_milestone_key

    if is_epic_dev_complete_query(query):
        return "feature_freeze"
    key = testplan_end_milestone_key(query)
    if key:
        return key
    return due_static_milestone_key(query)


def ends_at_feature_freeze(query: str) -> bool:
    """Checks that run through Feature Freeze day only (not after)."""
    return check_end_milestone_key(query) == "feature_freeze"
