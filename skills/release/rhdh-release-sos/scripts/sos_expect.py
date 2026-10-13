"""Expectation checks for SoS reports (`expect …` queries)."""

from __future__ import annotations

import re

JIRA_BROWSE_BASE = "https://redhat.atlassian.net/browse/"

_EXPECT_ASSIGNEE = re.compile(
    r'^expect\s+assignee\s+summary\s+~\s+"([^"]+)"(?:\s+\+\s+(.+))?$',
    re.IGNORECASE,
)
_ASSIGNEE_MATCH_LIMIT = 2
_UNASSIGNED = frozenset({"", "unassigned"})


def is_expect_query(query: str) -> bool:
    return query.strip().lower().startswith("expect ")


def is_expect_assignee_query(query: str) -> bool:
    return _EXPECT_ASSIGNEE.match(query.strip()) is not None


def parse_expect_assignee_query(query: str) -> tuple[str, str | None]:
    match = _EXPECT_ASSIGNEE.match(query.strip())
    if not match:
        raise ValueError(f"Not an expect assignee query: {query!r}")
    pattern = match.group(1)
    extra = (match.group(2) or "").strip() or None
    return pattern, extra


def expect_assignee_summary_pattern(query: str) -> str:
    pattern, _extra = parse_expect_assignee_query(query)
    return pattern


def build_expect_assignee_jql(
    pattern: str,
    version: str,
    jql_mod,
    *,
    extra: str | None = None,
) -> str:
    """Compose JQL for one open issue matching summary and fixVersion."""
    escaped = pattern.replace("\\", "\\\\").replace('"', '\\"')
    fragment = f'summary ~ "{escaped}"'
    extra_parts = ["status != closed"]
    if extra:
        extra_parts.append(extra)
    return jql_mod.compose_fragment(fragment, version=version, extra=" AND ".join(extra_parts))


def issue_browse_url(key: str) -> str:
    return f"{JIRA_BROWSE_BASE}{key}" if key else ""


def evaluate_expect_assignee(issues: list[dict]) -> dict:
    """Turn search hits into report fields for an expect assignee check."""
    if not issues:
        return {
            "expect_state": "not_found",
            "summary": "Not found — create or link ticket",
            "issue_key": None,
            "issue_url": None,
            "assignee": None,
            "match_count": 0,
        }

    if len(issues) >= _ASSIGNEE_MATCH_LIMIT:
        keys = ", ".join(issue.get("key", "?") for issue in issues[:_ASSIGNEE_MATCH_LIMIT])
        return {
            "expect_state": "ambiguous",
            "summary": f"Multiple matches ({keys}) — pick one ticket",
            "issue_key": None,
            "issue_url": None,
            "assignee": None,
            "match_count": len(issues),
        }

    issue = issues[0]
    key = issue.get("key", "")
    assignee = (issue.get("assignee") or "").strip()
    issue_url = issue_browse_url(key)

    if assignee.lower() in _UNASSIGNED:
        return {
            "expect_state": "unassigned",
            "summary": "Unassigned — find an owner",
            "issue_key": key or None,
            "issue_url": issue_url or None,
            "assignee": None,
            "match_count": 1,
        }

    return {
        "expect_state": "assigned",
        "summary": f"Assigned ({key})",
        "issue_key": key or None,
        "issue_url": issue_url or None,
        "assignee": assignee,
        "match_count": 1,
    }
