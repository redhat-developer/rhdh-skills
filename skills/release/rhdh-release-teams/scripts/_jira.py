"""Field extraction and enrichment for acli Jira JSON.

`acli jira workitem search --json` returns only basic fields, and custom fields
are rejected by `--fields`, so every caller that needs team, story points, size,
or sprint has to enrich search results through `acli view` and then flatten the
nested payload.

Bundled with this skill so it runs installed alone. A sibling skill
carrying a copy of this file is expected, not a defect -- with one exception,
called out at FIELDS below.
"""

from __future__ import annotations

import json
import subprocess
import sys


def _f(issue, field, default=None):
    """Get field from issue.fields or top-level."""
    return issue.get("fields", {}).get(field, issue.get(field, default))


def _name(issue, field):
    """Get .name from a nested object field."""
    val = _f(issue, field)
    if isinstance(val, dict):
        return val.get("name", val.get("displayName", val.get("value", "")))
    return val if val is not None else ""


def _sprint_name(issue):
    """Extract active/future sprint name from sprint array."""
    sprints = _f(issue, "customfield_10020", [])
    if not sprints:
        return ""
    for state in ("active", "future"):
        for s in sprints:
            if isinstance(s, dict) and s.get("state") == state:
                return s.get("name", "")
    if isinstance(sprints[-1], dict):
        return sprints[-1].get("name", "")
    return ""


def _list_names(issue, field):
    """Join .name values from a list of objects."""
    items = _f(issue, field, [])
    return ", ".join(i.get("name", "") for i in items if isinstance(i, dict)) if items else ""


def _walk_adf(node, parts):
    if isinstance(node, dict):
        if node.get("type") == "text":
            text = node.get("text", "")
            if text:
                parts.append(text)
        for child in node.get("content", []):
            _walk_adf(child, parts)
    elif isinstance(node, list):
        for child in node:
            _walk_adf(child, parts)


def _adf_to_text(issue):
    """Extract plain text from ADF description."""
    desc = _f(issue, "description")
    if desc is None:
        return ""
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        parts = []
        _walk_adf(desc, parts)
        return " ".join(parts).strip()
    return str(desc)


# ---------------------------------------------------------------------------
# The `customfield_*` IDs below are live-Jira instance facts, not code. They
# must match the RHDH Jira site, and a stale copy fails SILENTLY: the extractor
# reads a field that does not exist and yields "" or None, so the caller reports
# missing data instead of an error. `_sprint_name` above carries one too
# (customfield_10020).
#
# Authoritative table:  skills/reference/rhdh-jira-context/references/fields.md
# Check a copy against live Jira:
#     acli jira workitem view RHIDP-1 --fields '*all' --json
#
# The duplication is deliberate — this script must run installed alone. Guard:
#     skills/reference/rhdh-jira-api/scripts/validate_field_ids.py
# Run it with no arguments to check every copy against fields.md offline, or with
# --live to check fields.md against Jira. Run it after editing any ID here.
# ---------------------------------------------------------------------------
FIELDS = {
    # Core
    "key": lambda i: i.get("key", ""),
    "summary": lambda i: _f(i, "summary", ""),
    "status": lambda i: _name(i, "status"),
    "assignee": lambda i: _name(i, "assignee"),
    "assignee_email": lambda i: (
        _f(i, "assignee", {}).get("emailAddress", "") if isinstance(_f(i, "assignee"), dict) else ""
    ),
    "reporter": lambda i: _name(i, "reporter"),
    "issuetype": lambda i: _name(i, "issuetype"),
    "priority": lambda i: _name(i, "priority"),
    "project": lambda i: (
        _f(i, "project", {}).get("key", "")
        if isinstance(_f(i, "project"), dict)
        else str(_f(i, "project", ""))
    ),
    "created": lambda i: _f(i, "created", ""),
    "updated": lambda i: _f(i, "updated", ""),
    # Custom -- see the warning above before editing any customfield_* ID
    "team": lambda i: _name(i, "customfield_10001"),
    "story_points": lambda i: _f(i, "customfield_10028"),
    "size": lambda i: _name(i, "customfield_10795"),
    "sprint": _sprint_name,
    "parent": lambda i: (
        _f(i, "parent", {}).get("key", "") if isinstance(_f(i, "parent"), dict) else ""
    ),
    "rn_type": lambda i: _name(i, "customfield_10785"),
    "fix_versions": lambda i: _list_names(i, "fixVersions"),
    "components": lambda i: _list_names(i, "components"),
    "labels": lambda i: ", ".join(_f(i, "labels", []) or []),
    "description": _adf_to_text,
    "security": lambda i: _name(i, "security"),
    "feature_status": lambda i: _name(i, "customfield_10807"),
    "link_count": lambda i: len(_f(i, "issuelinks", []) or []),
}


def enrich(issues, acli_path, *, progress=True):
    """Fetch full field data for each issue via acli view."""
    enriched = []
    total = len(issues)
    for idx, issue in enumerate(issues, 1):
        key = issue.get("key", "")
        if not key:
            continue
        if progress:
            print(f"\r  Enriching {idx}/{total}: {key}...", end="", file=sys.stderr)
        try:
            result = subprocess.run(
                [acli_path, "jira", "workitem", "view", key, "--fields", "*all", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                enriched.append(data[0] if isinstance(data, list) else data)
            else:
                enriched.append(issue)
                if progress:
                    print(" [failed]", file=sys.stderr)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            enriched.append(issue)
    if progress:
        print(file=sys.stderr)  # newline after progress
    return enriched


def flatten(issue, fields):
    """Extract fields into a flat dict."""
    row = {}
    for f in fields:
        ext = FIELDS.get(f)
        val = ext(issue) if ext else _f(issue, f, "")
        row[f] = val if val is not None else ""
    return row
