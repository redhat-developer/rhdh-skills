"""Normalize Jira REST issues for signal evaluation."""

from __future__ import annotations

from typing import Any


def _field(issue: dict, name: str, default=None):
    return issue.get("fields", {}).get(name, default)


def _name(obj: Any) -> str:
    if isinstance(obj, dict):
        return obj.get("name", obj.get("displayName", "")) or ""
    return ""


def normalize(issue: dict) -> dict:
    itype = _name(_field(issue, "issuetype"))
    priority = _name(_field(issue, "priority"))
    assignee = _field(issue, "assignee")
    sp = _field(issue, "customfield_10028")
    return {
        "key": issue.get("key", ""),
        "summary": _field(issue, "summary", ""),
        "status": _name(_field(issue, "status")),
        "issuetype": itype,
        "priority": priority,
        "assigned": assignee is not None,
        "story_points": sp,
        "parent": (_field(issue, "parent") or {}).get("key", ""),
    }


def normalize_fixture(rows: list[dict]) -> list[dict]:
    """Test helper: rows already flat."""
    return rows
