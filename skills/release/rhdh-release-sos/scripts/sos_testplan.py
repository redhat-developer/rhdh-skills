"""Test Plan epic checks for SoS reports (`testplan …` queries)."""

from __future__ import annotations

import re

JIRA_BROWSE_BASE = "https://redhat.atlassian.net/browse/"

_TESTPLAN = re.compile(
    r'^testplan\s+(?P<kind>children assigned|signoff open)\s+summary\s+~\s+"([^"]+)"'
    r"(?:\s+\+\s+(.+))?$",
    re.IGNORECASE,
)
_EPIC_MATCH_LIMIT = 2
_CHILD_SEARCH_LIMIT = 500
_UNASSIGNED = frozenset({"", "unassigned"})
_CLOSED = frozenset({"closed"})


def is_testplan_query(query: str) -> bool:
    return _TESTPLAN.match(query.strip()) is not None


def parse_testplan_query(query: str) -> tuple[str, str, str | None]:
    match = _TESTPLAN.match(query.strip())
    if not match:
        raise ValueError(f"Not a testplan query: {query!r}")
    kind = match.group("kind").strip().lower()
    pattern = match.group(2)
    extra = (match.group(3) or "").strip() or None
    return kind, pattern, extra


def testplan_kind(query: str) -> str | None:
    if not is_testplan_query(query):
        return None
    kind, _pattern, _extra = parse_testplan_query(query)
    return kind


def testplan_end_milestone_key(query: str) -> str | None:
    if is_testplan_query(query):
        return "feature_freeze"
    return None


def build_testplan_epic_jql(
    pattern: str, version: str, jql_mod, *, extra: str | None = None
) -> str:
    escaped = pattern.replace("\\", "\\\\").replace('"', '\\"')
    fragment = f'summary ~ "{escaped}"'
    extra_parts = ["issuetype = Epic", "status != closed"]
    if extra:
        extra_parts.append(extra)
    return jql_mod.compose_fragment(fragment, version=version, extra=" AND ".join(extra_parts))


def issue_browse_url(key: str) -> str:
    return f"{JIRA_BROWSE_BASE}{key}" if key else ""


def normalize_issue_row(issue: dict) -> dict:
    key = issue.get("key", "")
    return {
        "key": key,
        "summary": issue.get("summary", ""),
        "status": issue.get("status", ""),
        "assignee": (issue.get("assignee") or "").strip(),
        "url": issue_browse_url(key),
    }


def resolve_testplan_epic(epics: list[dict]) -> dict:
    if not epics:
        return {
            "state": "not_found",
            "summary": "Test Plan epic not found",
            "epic_key": None,
            "epic_url": None,
        }
    if len(epics) >= _EPIC_MATCH_LIMIT:
        keys = ", ".join(issue.get("key", "?") for issue in epics[:_EPIC_MATCH_LIMIT])
        return {
            "state": "ambiguous",
            "summary": f"Multiple Test Plan epics ({keys}) — pick one",
            "epic_key": None,
            "epic_url": None,
        }
    epic = epics[0]
    key = epic.get("key", "")
    return {
        "state": "ok",
        "summary": key,
        "epic_key": key or None,
        "epic_url": issue_browse_url(key),
    }


def evaluate_children_assigned(children: list[dict]) -> dict:
    rows = [normalize_issue_row(issue) for issue in children]
    unassigned = [row for row in rows if (row.get("assignee") or "").strip().lower() in _UNASSIGNED]
    total = len(rows)
    if total == 0:
        return {
            "state": "ok",
            "summary": "No open tasks",
            "child_count": 0,
            "unassigned_count": 0,
        }
    if not unassigned:
        label = "task" if total == 1 else "tasks"
        return {
            "state": "ok",
            "summary": f"All assigned ({total} {label})",
            "child_count": total,
            "unassigned_count": 0,
        }
    count = len(unassigned)
    label = "task" if count == 1 else "tasks"
    return {
        "state": "action_needed",
        "summary": f"{count} unassigned {label}",
        "child_count": total,
        "unassigned_count": count,
    }


def evaluate_signoff_open(signoff_tasks: list[dict]) -> dict:
    rows = [normalize_issue_row(issue) for issue in signoff_tasks]
    open_rows = [row for row in rows if (row.get("status") or "").strip().lower() not in _CLOSED]
    total = len(rows)
    if total == 0:
        return {
            "state": "action_needed",
            "summary": "No sign-off tasks — add sign-off steps",
            "signoff_count": 0,
            "open_count": 0,
            "issues": [],
        }
    if not open_rows:
        label = "task" if total == 1 else "tasks"
        return {
            "state": "ok",
            "summary": f"Signed off ({total} {label})",
            "signoff_count": total,
            "open_count": 0,
            "issues": [],
        }
    count = len(open_rows)
    label = "task" if count == 1 else "tasks"
    return {
        "state": "action_needed",
        "summary": f"{count} sign-off {label} open",
        "signoff_count": total,
        "open_count": count,
        "issues": open_rows,
    }


def children_jql(epic_key: str) -> str:
    return f"parent = {epic_key} AND issuetype in (Task, Sub-task) AND status != closed"


def unassigned_children_jql(epic_key: str) -> str:
    return (
        f"parent = {epic_key} AND issuetype in (Task, Sub-task) AND status != closed "
        f"AND assignee is EMPTY"
    )


def signoff_tasks_jql(epic_key: str) -> str:
    return f'parent = {epic_key} AND summary ~ "sign-off"'


def signoff_open_jql(epic_key: str) -> str:
    return f'parent = {epic_key} AND summary ~ "sign-off" AND status != Closed'
