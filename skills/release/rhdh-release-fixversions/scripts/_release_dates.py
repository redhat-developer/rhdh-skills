"""Read milestone dates from the RHDHPLAN release Feature description."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Shared ADF milestone parsing lives in rhdh-jira-api (requiresSkills dependency).
_jira_api_scripts = Path(__file__).resolve().parents[3] / "reference" / "rhdh-jira-api" / "scripts"
if str(_jira_api_scripts) not in sys.path:
    sys.path.insert(0, str(_jira_api_scripts))

from adf_milestones import extract_milestone_dates  # noqa: E402

JIRA_BROWSE_BASE = "https://issues.redhat.com/browse"


def release_feature_jql(version: str) -> str:
    return (
        "project = RHDHPLAN AND issuetype = Feature AND component = Release "
        f'AND summary ~ "{version}" ORDER BY created DESC'
    )


def pick_release_issue(issues: list[dict[str, Any]], version: str) -> dict[str, Any] | None:
    if not issues:
        return None
    for issue in issues:
        summary = issue.get("fields", {}).get("summary", "")
        if version in summary:
            return issue
    return issues[0]


def release_feature_status_fields(issue: dict[str, Any]) -> dict[str, str]:
    status = issue.get("fields", {}).get("status") or {}
    status_name = status.get("name", "")
    status_category = (status.get("statusCategory") or {}).get("key", "")
    return {"status": status_name, "status_category": status_category}


def release_feature_is_closed(feature: dict[str, Any] | None) -> bool:
    if not feature:
        return False
    category = (feature.get("status_category") or "").lower()
    if category == "done":
        return True
    return (feature.get("status") or "").lower() == "closed"


def lookup_release_feature(client: Any, version: str) -> dict[str, Any] | None:
    """Return the RHDHPLAN release Feature issue for a version, including status."""
    issues = client.search_issues(
        release_feature_jql(version),
        max_results=5,
        fields="summary,description,status",
    )
    issue = pick_release_issue(issues, version)
    if issue is None:
        return None
    key = issue.get("key", "")
    summary = issue.get("fields", {}).get("summary", "")
    status_fields = release_feature_status_fields(issue)
    return {
        "found": True,
        "issue_key": key,
        "issue_url": f"{JIRA_BROWSE_BASE}/{key}",
        "summary": summary,
        "status": status_fields["status"],
        "status_category": status_fields["status_category"],
        "is_closed": release_feature_is_closed(status_fields),
    }


def lookup_release_doc(client: Any, version: str) -> dict[str, Any] | None:
    """Return release Feature milestones when a matching RHDHPLAN issue exists."""
    issues = client.search_issues(
        release_feature_jql(version),
        max_results=5,
        fields="summary,description,status",
    )
    issue = pick_release_issue(issues, version)
    if issue is None:
        return None
    key = issue.get("key", "")
    summary = issue.get("fields", {}).get("summary", "")
    description = issue.get("fields", {}).get("description")
    if not isinstance(description, dict):
        detail = client.get_issue(key, fields="description,status")
        description = detail.get("fields", {}).get("description")
        status_fields = release_feature_status_fields(detail)
    else:
        status_fields = release_feature_status_fields(issue)
    milestones = extract_milestone_dates(description)
    has_date = any(value != "TBD" for value in milestones.values())
    base = {
        "issue_key": key,
        "issue_url": f"{JIRA_BROWSE_BASE}/{key}",
        "summary": summary,
        "status": status_fields["status"],
        "status_category": status_fields["status_category"],
        "is_closed": release_feature_is_closed(status_fields),
        "milestones": milestones,
        "has_usable_dates": has_date,
    }
    return base
