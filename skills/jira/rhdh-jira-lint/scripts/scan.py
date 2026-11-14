#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Scan RHDH Jira for lint findings and propose the standard remediation.

Read-only. This is the deterministic half of the hygiene sweep: it applies the
same rules as the RHDH Jira lint job and emits one JSON finding per violation,
each carrying the action class the remediation SOP assigns to it and the person
to mention in the receipt comment.

Custom field IDs are resolved by name at run time, never hard-coded, so a field
that moved is reported instead of silently read as empty.

Usage:
  uv run scripts/scan.py --assignee me
  uv run scripts/scan.py --team "RHDH Install"
  uv run scripts/scan.py --release 1.10.0
  uv run scripts/scan.py --keys RHIDP-1234,RHIDP-1235 --md
  uv run scripts/scan.py --jql "project = RHIDP AND sprint in openSprints()"

The release calendar resolves in this order: --release-calendar, then
JIRA_LINT_RELEASE_CALENDAR, then ./release_calendar.yaml. Without one, the
freeze and release-note rules do not run and the report says so.

Token discovery: JIRA_TOKEN_FILE if set, otherwise `.jira-token` next to the
real acli binary. Format is one line `email:token`. Never printed.
Optional JIRA_BASE_URL (default https://redhat.atlassian.net).

Exit codes: 0 findings or none; 2 usage; 3 no credentials; 4 Jira request failed.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_BASE = "https://redhat.atlassian.net"
PROJECTS = ("RHIDP", "RHDHPLAN", "RHDHBUGS")
EXCLUDED_STATUSES = ("Closed", "Release Pending")
DOCS_TEAM = "RHIDP - Documentation"
WAIVER_LABEL = "hygiene-waived"
RN_NOT_REQUIRED = "Release Note Not Required"
SEARCH_BOUND = "updated >= -365d"
CALENDAR_ENV = "JIRA_LINT_RELEASE_CALENDAR"
CALENDAR_FILE = "release_calendar.yaml"

# Resolved by name against GET /rest/api/3/field. Alternatives cover the naming
# drift seen between the Cloud and legacy instances.
FIELD_NAMES: dict[str, tuple[str, ...]] = {
    "team": ("Team",),
    "size": ("Size", "T-Shirt Size", "T-shirt size"),
    "story_points": ("Story Points", "Story point estimate"),
    "rn_type": ("Release Note Type",),
    "rn_text": ("Release Note Text",),
    "rn_status": ("Release Note Status",),
}

SEARCH_FIELDS = [
    "summary",
    "status",
    "issuetype",
    "priority",
    "components",
    "fixVersions",
    "project",
    "assignee",
    "reporter",
    "parent",
    "labels",
    "description",
    "updated",
]


class ScanError(RuntimeError):
    """A request or configuration failure that must not look like a finding."""

    def __init__(self, message: str, *, status: int | None = None, code: int = 4):
        super().__init__(message)
        self.status = status
        self.code = code


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #


def find_token_file(acli_path: str | None = None) -> Path | None:
    """Return the token path if the file exists. Never read its contents here."""
    override = os.environ.get("JIRA_TOKEN_FILE")
    if override:
        path = Path(override)
        return path if path.is_file() else None
    if not acli_path:
        acli_path = shutil.which("acli")
    if not acli_path:
        return None
    token_path = Path(acli_path).resolve().parent / ".jira-token"
    return token_path if token_path.is_file() else None


def load_email_token(acli_path: str | None = None) -> str:
    """Return the `email:token` line for Basic auth. Never print it."""
    path = find_token_file(acli_path)
    if path is None:
        raise ScanError(
            "Jira token file not found next to acli (or JIRA_TOKEN_FILE). "
            "Run /setup-rhdh-skills atlassian-mcp or authenticate acli.",
            code=3,
        )
    try:
        line = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError) as exc:
        raise ScanError(f"could not read the Jira token file: {exc}", code=3) from exc
    if ":" not in line:
        raise ScanError(
            "the Jira token file is not in `email:token` form; a bare token 401s",
            code=3,
        )
    return line


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


def _request(
    base: str,
    path: str,
    credential: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> Any:
    url = f"{base.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    encoded = base64.b64encode(credential.encode("utf-8")).decode("ascii")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Basic {encoded}")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise ScanError(
            f"{method} {path} failed with HTTP {exc.code}: {detail}",
            status=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        raise ScanError(f"{method} {path} could not reach Jira: {exc.reason}") from exc
    return json.loads(payload) if payload.strip() else None


def resolve_fields(base: str, credential: str) -> tuple[dict[str, str], list[str]]:
    """Map each logical field to its live custom-field id."""
    raw = _request(base, "/rest/api/3/field", credential) or []
    by_name: dict[str, str] = {}
    for field in raw:
        name = str(field.get("name") or "").strip().lower()
        field_id = field.get("id")
        if name and isinstance(field_id, str) and field_id.startswith("customfield_"):
            by_name.setdefault(name, field_id)

    resolved: dict[str, str] = {}
    missing: list[str] = []
    for key, names in FIELD_NAMES.items():
        for name in names:
            field_id = by_name.get(name.lower())
            if field_id:
                resolved[key] = field_id
                break
        else:
            missing.append(key)
    return resolved, missing


def _search_enhanced(
    base: str, credential: str, jql: str, fields: list[str], page_size: int, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    issues: list[dict[str, Any]] = []
    next_token: str | None = None
    while True:
        body: dict[str, Any] = {"jql": jql, "maxResults": page_size, "fields": fields}
        if next_token:
            body["nextPageToken"] = next_token
        payload = _request(base, "/rest/api/3/search/jql", credential, method="POST", body=body)
        batch = payload.get("issues") or []
        issues.extend(batch)
        next_token = payload.get("nextPageToken")
        if len(issues) >= limit:
            return issues[:limit], True
        if not next_token or payload.get("isLast"):
            return issues, False


def _search_classic(
    base: str, credential: str, jql: str, fields: list[str], page_size: int, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    issues: list[dict[str, Any]] = []
    start_at = 0
    while True:
        body = {"jql": jql, "startAt": start_at, "maxResults": page_size, "fields": fields}
        payload = _request(base, "/rest/api/3/search", credential, method="POST", body=body)
        batch = payload.get("issues") or []
        issues.extend(batch)
        start_at += len(batch)
        if len(issues) >= limit:
            return issues[:limit], True
        if not batch or start_at >= int(payload.get("total") or 0):
            return issues, False


def search_issues(
    base: str, credential: str, jql: str, fields: list[str], page_size: int = 100, limit: int = 500
) -> tuple[list[dict[str, Any]], bool]:
    """Prefer the token-paginated endpoint, fall back to startAt on rejection."""
    try:
        return _search_enhanced(base, credential, jql, fields, page_size, limit)
    except ScanError as exc:
        if exc.status not in (400, 404, 410):
            raise
        return _search_classic(base, credential, jql, fields, page_size, limit)


# --------------------------------------------------------------------------- #
# Field helpers
# --------------------------------------------------------------------------- #


def has_value(raw: Any) -> bool:
    """True when Jira returned something a person would call set."""
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    if isinstance(raw, str):
        return bool(raw.strip())
    if isinstance(raw, dict):
        if "value" in raw:
            return has_value(raw["value"])
        if "name" in raw:
            return has_value(raw["name"])
        return any(has_value(value) for value in raw.values())
    if isinstance(raw, (list, tuple)):
        return any(has_value(item) for item in raw)
    return bool(str(raw).strip())


def _flatten_adf(node: Any) -> str:
    """Flatten an Atlassian Document Format body to newline-separated text."""
    if isinstance(node, list):
        return "\n".join(_flatten_adf(item) for item in node)
    if not isinstance(node, dict):
        return str(node) if node is not None else ""
    if node.get("type") == "text":
        return str(node.get("text") or "")
    blocks = {
        "doc",
        "paragraph",
        "heading",
        "listItem",
        "bulletList",
        "orderedList",
        "blockquote",
        "codeBlock",
        "tableRow",
    }
    parts: list[str] = []
    for child in node.get("content") or []:
        text = _flatten_adf(child)
        if text:
            parts.append(text)
    separator = "\n" if node.get("type") in blocks else " "
    rendered = separator.join(part for part in parts if part)
    if node.get("type") == "listItem":
        return f"- {rendered}"
    return rendered


def description_text(fields: dict[str, Any]) -> str:
    raw = fields.get("description")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return _flatten_adf(raw)
    return ""


def text_nonempty(raw: Any) -> bool:
    """A text field is set when it has content, not when it has structure.

    An empty ADF document is a dict with a `version` key, so `has_value` would
    call it populated. Release Note Text is the field where that matters.
    """
    if isinstance(raw, dict) and raw.get("type") == "doc":
        return bool(_flatten_adf(raw).strip())
    if isinstance(raw, str):
        return bool(raw.strip())
    return has_value(raw)


def acceptance_criteria_count(text: str) -> int:
    """Count bullet or numbered items in the acceptance-criteria section."""
    match = re.search(r"acceptance\s+criteria", text, re.IGNORECASE)
    section = text[match.end() :] if match else text
    section = section[:4000]
    return len(re.findall(r"(?m)^\s*(?:[-*]|\d+[.)])\s+\S", section))


def _names(values: Any, key: str = "name") -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value.get(key)) for value in values if isinstance(value, dict) and value.get(key)]


def team_names(fields: dict[str, Any], team_ids: list[str]) -> list[str]:
    names: list[str] = []
    for field_id in team_ids:
        raw = fields.get(field_id)
        candidates = raw if isinstance(raw, list) else [raw]
        for candidate in candidates:
            if isinstance(candidate, dict):
                for key in ("name", "title", "value"):
                    if candidate.get(key):
                        names.append(str(candidate[key]))
                        break
            elif candidate:
                names.append(str(candidate))
    return names


def is_docs_team(fields: dict[str, Any], team_ids: list[str]) -> bool:
    return any(DOCS_TEAM in name for name in team_names(fields, team_ids))


def is_release_component(fields: dict[str, Any]) -> bool:
    return "Release" in _names(fields.get("components"))


def mention_for(fields: dict[str, Any]) -> dict[str, str] | None:
    """The person the receipt comment should notify: assignee, else reporter."""
    assignee = fields.get("assignee") or {}
    reporter = fields.get("reporter") or {}
    actor = assignee or reporter
    account_id = actor.get("accountId")
    if not account_id:
        return None
    return {
        "accountId": str(account_id),
        "displayName": str(actor.get("displayName") or actor.get("emailAddress") or ""),
        "role": "assignee" if assignee else "reporter",
    }


# --------------------------------------------------------------------------- #
# Release calendar and phases
# --------------------------------------------------------------------------- #


def discover_calendar(explicit: str | None) -> str | None:
    """Resolve the release calendar without requiring an argument.

    The lint job reads the file from its own checkout. An autonomous runner has
    no such checkout, so it names the source in one place: the flag, the
    environment, or the working directory.
    """
    if explicit:
        return explicit
    from_env = os.environ.get(CALENDAR_ENV)
    if from_env:
        return from_env
    if Path(CALENDAR_FILE).is_file():
        return CALENDAR_FILE
    return None


def _iso_date(raw: Any) -> str | None:
    """Accept only a real YYYY-MM-DD. A TBD or a natural-language date is not a date."""
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _normalize_calendar(
    raw: dict[str, Any],
) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    """Map either calendar shape onto the three keys the rules need.

    Accepts the `release_calendar.yaml` mapping and the JSON `/rhdh-release-schedule`
    returns, so the skill can discover dates itself instead of requiring a file
    produced outside it. `ga_push` is the GA announce date, never Go/No Go.
    """
    calendar: dict[str, dict[str, str]] = {}
    problems: list[dict[str, Any]] = []
    for version, entry in raw.items():
        if not isinstance(version, str) or not version.strip():
            continue
        if not isinstance(entry, dict):
            problems.append({"version": version, "missing": ["all"], "reason": "not an object"})
            continue
        dates = {
            "feature_freeze": _iso_date(entry.get("feature_freeze")),
            "code_freeze": _iso_date(entry.get("code_freeze")),
            "ga_push": _iso_date(entry.get("ga_push") or entry.get("ga_announce")),
        }
        missing = [key for key, value in dates.items() if not value]
        if missing:
            decided = any(value for value in dates.values())
            problems.append(
                {
                    "version": version.strip(),
                    "missing": missing,
                    "reason": "partly decided" if decided else "not decided",
                }
            )
            continue
        calendar[version.strip()] = {key: str(value) for key, value in dates.items()}
    return calendar, problems


def _calendar_from_json(payload: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Unwrap the two JSON shapes the release skills emit."""
    problems: list[dict[str, Any]] = []
    if isinstance(payload, list):
        releases = payload
    elif isinstance(payload, dict) and isinstance(payload.get("releases"), list):
        releases = payload["releases"]
    elif isinstance(payload, dict) and isinstance(payload.get("releases"), dict):
        return payload["releases"], problems
    elif isinstance(payload, dict):
        return payload, problems
    else:
        raise ScanError("release calendar JSON is not an object or a release list", code=2)

    mapped: dict[str, Any] = {}
    for release in releases:
        if not isinstance(release, dict):
            problems.append({"version": "?", "missing": ["all"], "reason": "not an object"})
            continue
        version = release.get("version") or release.get("name")
        if not version:
            problems.append({"version": "?", "missing": ["version"], "reason": "no version"})
            continue
        mapped[str(version)] = release
    return mapped, problems


def load_release_calendar(
    path: str | Path,
) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    """Load the calendar from YAML or the JSON the release skills return.

    Returns the usable entries and the versions that could not be used, so an
    incomplete calendar is reported rather than silently enforcing nothing.
    """
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    is_json = str(path).lower().endswith(".json") or stripped.startswith(("{", "["))

    if is_json:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScanError(f"release calendar {path} is not valid JSON: {exc}", code=2) from exc
        raw, problems = _calendar_from_json(payload)
        calendar, more = _normalize_calendar(raw)
        return calendar, [*problems, *more]

    releases: dict[str, dict[str, str]] = {}
    problems: list[dict[str, Any]] = []
    current: str | None = None
    version_key = re.compile(r'^\s{2}"?([0-9][0-9.]*)"?\s*:\s*$')
    date_key = re.compile(r"^\s{4}(feature_freeze|code_freeze|ga_push)\s*:\s*(.*?)\s*$")
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        version_match = version_key.match(line)
        if version_match:
            current = version_match.group(1)
            releases[current] = {}
            continue
        date_match = date_key.match(line)
        if date_match and current:
            value = date_match.group(2).split("#", 1)[0].strip().strip("\"'")
            releases[current][date_match.group(1)] = value
    calendar, more = _normalize_calendar(releases)
    return calendar, [*problems, *more]


def release_phase(
    version: str | None, calendar: dict[str, dict[str, str]], today: date
) -> tuple[str | None, str | None]:
    """Return (phase, boundary-date) exactly as the lint job computes it."""
    if not version or version not in calendar:
        return None, None
    dates = calendar[version]
    try:
        feature_freeze = datetime.strptime(dates["feature_freeze"], "%Y-%m-%d").date()
        code_freeze = datetime.strptime(dates["code_freeze"], "%Y-%m-%d").date()
        ga_push = datetime.strptime(dates["ga_push"], "%Y-%m-%d").date()
    except (KeyError, ValueError):
        return None, None
    if today >= ga_push:
        return "GA Push", dates["ga_push"]
    if today >= code_freeze:
        return "Code Freeze", dates["code_freeze"]
    if today >= feature_freeze:
        return "Feature Freeze", dates["feature_freeze"]
    return "Development", None


def active_versions(calendar: dict[str, dict[str, str]], today: date) -> list[str]:
    return [
        version
        for version in calendar
        if release_phase(version, calendar, today)[0]
        in ("Feature Freeze", "Code Freeze", "GA Push")
    ]


# --------------------------------------------------------------------------- #
# Rule evaluation
# --------------------------------------------------------------------------- #


def _finding(
    issue: dict[str, Any],
    rule: str,
    *,
    field: str,
    action: str,
    severity: str,
    detail: str,
    evidence: dict[str, Any] | None = None,
    proposed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    key = issue.get("key")
    return {
        "rule": rule,
        "key": key,
        "url": f"https://redhat.atlassian.net/browse/{key}",
        "project": (fields.get("project") or {}).get("key"),
        "type": (fields.get("issuetype") or {}).get("name"),
        "status": (fields.get("status") or {}).get("name"),
        "assignee": (fields.get("assignee") or {}).get("emailAddress"),
        "reporter": (fields.get("reporter") or {}).get("emailAddress"),
        "mention": mention_for(fields),
        "summary": fields.get("summary"),
        "field": field,
        "action": action,
        "severity": severity,
        "detail": detail,
        "evidence": evidence or {},
        "proposed": proposed,
    }


def excluded(issue: dict[str, Any]) -> bool:
    fields = issue.get("fields") or {}
    issue_type = fields.get("issuetype") or {}
    status = (fields.get("status") or {}).get("name")
    summary = str(fields.get("summary") or "").lower()
    return bool(
        issue_type.get("subtask")
        or status in EXCLUDED_STATUSES
        or issue_type.get("name") == "Outcome"
        or "[test execution]" in summary
    )


def waiver_for(labels: Any) -> tuple[bool, str | None]:
    """Return (waived, expiry) for the hygiene-waived label family.

    `hygiene-waived` never expires. `hygiene-waived-YYYY-MM` expires at the end
    of that month, so a deliberate blank is revisited instead of nagged about.
    """
    if not isinstance(labels, list):
        return False, None
    expiry: str | None = None
    waived = False
    for label in labels:
        if label == WAIVER_LABEL:
            waived = True
        elif isinstance(label, str) and label.startswith(f"{WAIVER_LABEL}-"):
            suffix = label[len(WAIVER_LABEL) + 1 :]
            match = re.fullmatch(r"(\d{4})-(\d{2})", suffix)
            if not match:
                continue
            year, month = int(match.group(1)), int(match.group(2))
            if not 1 <= month <= 12:
                continue
            ends = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).isoformat()
            waived = True
            expiry = ends
    return waived, expiry


def _waiver_state(issue: dict[str, Any], today: date) -> tuple[bool, str | None, bool]:
    """Return (waived, expiry, expired)."""
    waived, expiry = waiver_for((issue.get("fields") or {}).get("labels"))
    if not waived:
        return False, None, False
    expired = bool(expiry and datetime.strptime(expiry, "%Y-%m-%d").date() < today)
    return waived, expiry, expired


def evaluate(issue: dict[str, Any], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply the lint rule set to one issue and return its findings."""
    if excluded(issue):
        return []

    fields = issue.get("fields") or {}
    issue_type = (fields.get("issuetype") or {}).get("name", "")
    key = issue.get("key")
    project = (fields.get("project") or {}).get("key", "")
    finders = ctx["fields"]
    calendar: dict[str, dict[str, str]] = ctx.get("calendar") or {}
    today: date = ctx["today"]
    parents: dict[str, dict[str, Any]] = ctx.get("parents") or {}
    parent_key = ((fields.get("parent") or {}) or {}).get("key")
    parent = parents.get(parent_key) if parent_key else None
    parent_fields = (parent or {}).get("fields") or {}
    docs_team = is_docs_team(fields, [finders["team"]] if "team" in finders else [])
    release_component = is_release_component(fields)
    findings: list[dict[str, Any]] = []
    text = description_text(fields)
    ac_count = acceptance_criteria_count(text)

    waiver_evidence = {"labels": fields.get("labels") or []}

    # Required on every issue type.
    if not has_value(fields.get("components")):
        parent_components = _names(parent_fields.get("components"))
        proposed = (
            {"fields": {"components": [{"name": name} for name in parent_components]}}
            if parent_components
            else None
        )
        findings.append(
            _finding(
                issue,
                "LINT-COMPONENT",
                field="Component/s",
                action="derive" if proposed else "choose",
                severity="error",
                detail=(
                    f"Inherited from {parent_key}."
                    if proposed
                    else "No parent component to inherit; needs an owner decision."
                ),
                evidence={
                    "current": [],
                    "parent": parent_key,
                    "parent_components": parent_components,
                    **waiver_evidence,
                },
                proposed=proposed,
            )
        )

    priority = (fields.get("priority") or {}).get("name")
    if not has_value(priority) or priority == "Undefined":
        parent_priority = (parent_fields.get("priority") or {}).get("name")
        proposed = (
            {"fields": {"priority": {"name": parent_priority}}}
            if has_value(parent_priority) and parent_priority != "Undefined"
            else None
        )
        findings.append(
            _finding(
                issue,
                "LINT-PRIORITY",
                field="Priority",
                action="derive" if proposed else "choose",
                severity="error",
                detail=(
                    f"Inherited from {parent_key}."
                    if proposed
                    else "No parent priority; Blocker and Critical are never inferred."
                ),
                evidence={
                    "current": priority or None,
                    "parent": parent_key,
                    "parent_priority": parent_priority,
                    **waiver_evidence,
                },
                proposed=proposed,
            )
        )

    size_id = finders.get("size")
    points_id = finders.get("story_points")
    if issue_type in ("Epic", "Feature"):
        if size_id and not has_value(fields.get(size_id)) and not docs_team:
            findings.append(
                _finding(
                    issue,
                    "LINT-SIZE",
                    field="Size",
                    action="estimate",
                    severity="warning",
                    detail="T-shirt size missing; estimate from the issue's own scope.",
                    evidence={
                        "current": None,
                        "acceptance_criteria": ac_count,
                        "description_chars": len(text.strip()),
                        "child_sizes": (ctx.get("children") or {}).get(key, {}),
                        **waiver_evidence,
                    },
                )
            )
    elif issue_type in ("Story", "Task", "Bug"):
        if points_id and not has_value(fields.get(points_id)) and not docs_team:
            findings.append(
                _finding(
                    issue,
                    "LINT-POINTS",
                    field="Story Points",
                    action="estimate",
                    severity="error",
                    detail="Story Points missing; estimate from scope, not from a guess.",
                    evidence={
                        "current": None,
                        "acceptance_criteria": ac_count,
                        "description_chars": len(text.strip()),
                        "is_spike": str(fields.get("summary") or "").upper().startswith("SPIKE:"),
                        **waiver_evidence,
                    },
                )
            )

    fix_versions = _names(fields.get("fixVersions"))
    if len(fix_versions) > 1:
        active = [
            version for version in fix_versions if version in active_versions(calendar, today)
        ]
        parent_versions = _names(parent_fields.get("fixVersions"))
        keep = (
            active[0]
            if len(active) == 1
            else (parent_versions[0] if len(parent_versions) == 1 else None)
        )
        proposed = {"fields": {"fixVersions": [{"name": keep}]}} if keep else None
        findings.append(
            _finding(
                issue,
                "LINT-FIXVERSION-MULTI",
                field="Fix Version/s",
                action="derive" if proposed else "choose",
                severity="error",
                detail=(
                    f"Keep {keep}; the other version is not the owner."
                    if proposed
                    else "Two or more plausible versions; the owner must pick."
                ),
                evidence={
                    "current": fix_versions,
                    "active_releases": active,
                    "parent_versions": parent_versions,
                    **waiver_evidence,
                },
                proposed=proposed,
            )
        )

    # Release-phase rules. One violation per rule even with several fix versions.
    seen: set[str] = set()
    for version in fix_versions:
        phase, boundary = release_phase(version, calendar, today)
        if phase is None or phase == "Development":
            continue
        if phase in ("Feature Freeze", "Code Freeze"):
            rule = "LINT-FF-PRIORITY" if phase == "Feature Freeze" else "LINT-CF-PRIORITY"
            allowed = ("Critical", "Blocker") if phase == "Feature Freeze" else ("Blocker",)
            if rule not in seen and not release_component and priority not in allowed:
                seen.add(rule)
                findings.append(
                    _finding(
                        issue,
                        rule,
                        field="Priority",
                        action="escalate",
                        severity="error",
                        detail=(
                            f"{phase} for {version} (since {boundary}); only "
                            f"{' or '.join(allowed)} may stay in progress."
                        ),
                        evidence={
                            "current": priority,
                            "fix_version": version,
                            "phase": phase,
                            "boundary": boundary,
                            "allowed": list(allowed),
                            "options": [
                                "move the fix version to a later release",
                                "escalate priority with the PM and Release Manager",
                                "descope from the release",
                            ],
                            **waiver_evidence,
                        },
                    )
                )
        if phase == "GA Push" and "LINT-GA-OPEN" not in seen:
            seen.add("LINT-GA-OPEN")
            findings.append(
                _finding(
                    issue,
                    "LINT-GA-OPEN",
                    field="Status",
                    action="escalate",
                    severity="error",
                    detail=f"GA has shipped for {version} (since {boundary}); the issue is still open.",
                    evidence={
                        "current": (fields.get("status") or {}).get("name"),
                        "fix_version": version,
                        "phase": phase,
                        "boundary": boundary,
                        "options": [
                            "close with the resolution that matches the outcome",
                            "move to a follow-up release if the work is real",
                        ],
                        **waiver_evidence,
                    },
                )
            )

    # Release-note rules for Features and Bugs after Feature Freeze.
    if issue_type in ("Feature", "Bug") and project in PROJECTS:
        phases = {
            phase
            for phase, _ in (release_phase(version, calendar, today) for version in fix_versions)
        }
        post_freeze = phases & {"Feature Freeze", "Code Freeze", "GA Push"}
        if post_freeze and not release_component:
            rn_type_id = finders.get("rn_type")
            rn_text_id = finders.get("rn_text")
            rn_status_id = finders.get("rn_status")
            rn_type = None
            if rn_type_id:
                raw = fields.get(rn_type_id)
                if isinstance(raw, dict):
                    rn_type = raw.get("value")
                elif raw:
                    rn_type = str(raw)
            rn_text = fields.get(rn_text_id) if rn_text_id else None
            rn_status = fields.get(rn_status_id) if rn_status_id else None
            phase_name = sorted(post_freeze)[0]
            evidence = {
                "phase": phase_name,
                "fix_versions": fix_versions,
                "rn_type": rn_type,
                "has_rn_text": text_nonempty(rn_text),
                "labels": fields.get("labels") or [],
            }

            if rn_type_id and not rn_type:
                findings.append(
                    _finding(
                        issue,
                        "LINT-RN-TYPE",
                        field="Release Note Type",
                        action="classify",
                        severity="warning",
                        detail=f"Required after {phase_name}; classify from the change itself.",
                        evidence=evidence,
                    )
                )
            if rn_text_id and rn_type != RN_NOT_REQUIRED and not text_nonempty(rn_text):
                findings.append(
                    _finding(
                        issue,
                        "LINT-RN-TEXT",
                        field="Release Note Text",
                        action="draft",
                        severity="warning",
                        detail="Release note text missing; draft it from the summary and outcome.",
                        evidence=evidence,
                    )
                )
            if rn_status_id and rn_type and rn_type != RN_NOT_REQUIRED and not has_value(rn_status):
                findings.append(
                    _finding(
                        issue,
                        "LINT-RN-STATUS",
                        field="Release Note Status",
                        action="derive",
                        severity="warning",
                        detail="Release Note Status must be Proposed once the note is written.",
                        evidence=evidence,
                        proposed={"fields": {rn_status_id: {"value": "Proposed"}}},
                    )
                )

    waived, expiry, expired = _waiver_state(issue, today)
    for finding in findings:
        finding["waived"] = waived and not expired
        finding["waiver_expires"] = expiry
        if waived and expired:
            finding["action"] = "review-waiver"
            finding["detail"] = (
                f"Waiver expired on {expiry}; re-decide or renew it. {finding['detail']}"
            )
    return findings


# --------------------------------------------------------------------------- #
# Collection
# --------------------------------------------------------------------------- #


def _children_index(issues: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Summarise sized children per parent, for Epic/Feature estimation."""
    index: dict[str, dict[str, Any]] = {}
    for issue in issues:
        fields = issue.get("fields") or {}
        parent_key = ((fields.get("parent") or {}) or {}).get("key")
        if not parent_key:
            continue
        bucket = index.setdefault(parent_key, {"count": 0, "sized": 0, "points": 0.0, "sizes": []})
        bucket["count"] += 1
        points = fields.get("story_points_value")
        size = fields.get("size_value")
        if isinstance(points, (int, float)) and points:
            bucket["sized"] += 1
            bucket["points"] += float(points)
        if size:
            bucket["sized"] += 1
            bucket["sizes"].append(size)
    return index


def _attach_values(issues: list[dict[str, Any]], finders: dict[str, str]) -> None:
    """Copy the resolved custom fields onto simple keys for evidence building."""
    for issue in issues:
        fields = issue.get("fields") or {}
        if size_id := finders.get("size"):
            raw = fields.get(size_id)
            fields["size_value"] = raw.get("value") if isinstance(raw, dict) else raw
        if points_id := finders.get("story_points"):
            fields["story_points_value"] = fields.get(points_id)


def build_jql(args: argparse.Namespace) -> str:
    if args.keys:
        keys = [key.strip() for key in args.keys.split(",") if key.strip()]
        return f"key in ({','.join(keys)})"
    if args.jql:
        return args.jql
    clauses = [f"project in ({','.join(PROJECTS)})", "status != Closed", SEARCH_BOUND]
    if args.assignee:
        assignee = "currentUser()" if args.assignee == "me" else f'"{args.assignee}"'
        clauses.insert(1, f"assignee = {assignee}")
    if args.release:
        clauses.append(f'fixVersion = "{args.release}"')
    return " AND ".join(clauses)


def collect(args: argparse.Namespace) -> dict[str, Any]:
    base = os.environ.get("JIRA_BASE_URL", DEFAULT_BASE).rstrip("/")
    credential = load_email_token()
    finders, missing = resolve_fields(base, credential)
    warnings: list[str] = []
    if missing:
        warnings.append(
            "fields not found by name, their rules are skipped: " + ", ".join(sorted(missing))
        )
    if "team" in missing:
        warnings.append(
            "Team field not found; the RHIDP - Documentation exemption did not run, "
            "so sizing findings may be false positives"
        )

    search_fields = list(dict.fromkeys([*SEARCH_FIELDS, *finders.values()]))
    jql = build_jql(args)
    issues, truncated = search_issues(
        base, credential, jql, search_fields, page_size=args.page_size, limit=args.limit
    )
    if truncated:
        warnings.append(
            f"stopped at the {args.limit}-issue limit; narrow the scope for a full sweep"
        )
    if args.team:
        wanted = args.team.strip().lower()
        team_id = finders.get("team")
        if not team_id:
            warnings.append("--team ignored: the Team field could not be resolved")
        else:
            issues = [
                issue
                for issue in issues
                if any(
                    name.lower() == wanted
                    for name in team_names(issue.get("fields") or {}, [team_id])
                )
            ]

    _attach_values(issues, finders)

    parent_keys = sorted(
        {
            ((issue.get("fields") or {}).get("parent") or {}).get("key")
            for issue in issues
            if ((issue.get("fields") or {}).get("parent") or {}).get("key")
        }
    )
    parents: dict[str, dict[str, Any]] = {}
    if parent_keys:
        parent_fields = list(
            dict.fromkeys(
                [
                    "summary",
                    "status",
                    "issuetype",
                    "priority",
                    "components",
                    "fixVersions",
                    *finders.values(),
                ]
            )
        )
        fetched, _ = search_issues(
            base,
            credential,
            f"key in ({','.join(parent_keys)})",
            parent_fields,
            page_size=args.page_size,
            limit=len(parent_keys),
        )
        parents = {issue.get("key"): issue for issue in fetched}

    calendar_path = discover_calendar(args.release_calendar)
    calendar: dict[str, dict[str, str]] = {}
    calendar_problems: list[dict[str, Any]] = []
    if calendar_path:
        try:
            calendar, calendar_problems = load_release_calendar(calendar_path)
        except (OSError, ScanError) as exc:
            warnings.append(f"release calendar could not be read: {exc}")
    for problem in calendar_problems:
        warnings.append(
            f"{problem['version']}: calendar entry {problem['reason']} "
            f"({', '.join(problem['missing'])}); rules needing it did not run"
        )
    if not calendar_path or not calendar:
        warnings.append(
            "no usable release calendar; freeze and release-note rules did not run "
            f"(scoped by --release-calendar, {CALENDAR_ENV}, or {CALENDAR_FILE})"
        )

    scoped_fix_versions = sorted(
        {
            version
            for issue in issues
            for version in _names((issue.get("fields") or {}).get("fixVersions"))
        }
    )
    calendar_missing_versions = [
        version for version in scoped_fix_versions if version not in calendar
    ]
    if calendar_missing_versions:
        shown = ", ".join(calendar_missing_versions[:10])
        suffix = "" if len(calendar_missing_versions) <= 10 else ", ..."
        warnings.append(
            f"{len(calendar_missing_versions)} fix version(s) in scope have no usable calendar "
            f"entry: {shown}{suffix}"
        )

    if args.today:
        try:
            today = datetime.strptime(args.today, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ScanError("--today must be YYYY-MM-DD", code=2) from exc
    else:
        today = date.today()
    ctx = {
        "fields": finders,
        "calendar": calendar,
        "today": today,
        "parents": parents,
        "children": _children_index(issues),
    }

    findings: list[dict[str, Any]] = []
    waived: list[dict[str, Any]] = []
    for issue in issues:
        for finding in evaluate(issue, ctx):
            if finding["waived"] and not args.include_waived:
                waived.append(finding)
            else:
                findings.append(finding)

    summary: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for finding in findings:
        summary[finding["rule"]] = summary.get(finding["rule"], 0) + 1
        by_action[finding["action"]] = by_action.get(finding["action"], 0) + 1

    return {
        "schema": 1,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "scope": {
            "jql": jql,
            "issues_scanned": len(issues),
            "truncated": truncated,
            "calendar": bool(calendar),
            "calendar_source": calendar_path,
            "calendar_problems": calendar_problems,
            "calendar_missing_versions": calendar_missing_versions,
            "today": today.isoformat(),
        },
        "fields": finders,
        "warnings": warnings,
        "summary": {"by_rule": summary, "by_action": by_action, "findings": len(findings)},
        "findings": findings,
        "waived": waived,
    }


def render_markdown(report: dict[str, Any]) -> str:
    scope = report["scope"]
    lines = [
        "## Jira lint",
        "",
        f"Scanned {scope['issues_scanned']} issues | "
        f"{report['summary']['findings']} findings | "
        f"{len(report['waived'])} waived",
        "",
        f"`{scope['jql']}`",
        "",
    ]
    for warning in report["warnings"]:
        lines.append(f"> {warning}")
    if report["warnings"]:
        lines.append("")
    if not report["findings"]:
        lines.append("No findings.")
        return "\n".join(lines)

    lines += [
        "| Issue | Rule | Field | Action | Detail |",
        "|-------|------|-------|--------|--------|",
    ]
    for finding in report["findings"]:
        detail = finding["detail"].replace("|", "\\|")
        lines.append(
            f"| [{finding['key']}]({finding['url']}) | {finding['rule']} | "
            f"{finding['field']} | {finding['action']} | {detail} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan RHDH Jira for lint findings.")
    parser.add_argument("--jql", help="Explicit JQL. Overrides the default scope.")
    parser.add_argument("--keys", help="Comma-separated issue keys.")
    parser.add_argument("--assignee", help="Email, or 'me' for the current user.")
    parser.add_argument("--team", help="Filter client-side by Jira team name.")
    parser.add_argument("--release", help="Restrict to one fix version.")
    parser.add_argument(
        "--release-calendar",
        help="release_calendar.yaml path. Defaults to $JIRA_LINT_RELEASE_CALENDAR or ./release_calendar.yaml.",
    )
    parser.add_argument("--today", help="YYYY-MM-DD override for release-phase tests.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum issues to scan.")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--include-waived", action="store_true", help="Report active waivers too.")
    parser.add_argument(
        "--md", action="store_true", help="Render a Markdown table instead of JSON."
    )
    args = parser.parse_args(argv)

    try:
        report = collect(args)
    except ScanError as exc:
        json.dump({"ok": False, "error": str(exc), "status": exc.status}, sys.stdout)
        sys.stdout.write("\n")
        return exc.code

    if args.md:
        print(render_markdown(report))
    else:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
