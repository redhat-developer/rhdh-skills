"""Resolve release milestones from Jira RHDHPLAN Feature ADF tables."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

_jira_api = Path(__file__).resolve().parents[2].parent / "reference" / "rhdh-jira-api" / "scripts"
if str(_jira_api) not in sys.path:
    sys.path.insert(0, str(_jira_api))

from adf_milestones import extract_milestone_dates  # noqa: E402

RELEASE_JQL = (
    "project=rhdhplan AND issuetype=feature AND component=release AND status != closed"
)


@dataclass(frozen=True)
class ReleaseContext:
    version: str
    feature_freeze: date | None
    code_freeze: date | None
    ga_date: date | None
    days_to_code_freeze: int | None
    phase: str | None          # "feature_freeze" | "code_freeze" | None
    phase_label: str | None    # "Feature Freeze" | "Code Freeze" | None
    freeze_warning: bool
    today: date


def resolve(fix_version: str, *, today: date | None = None, warning_days: int = 14) -> ReleaseContext:
    today = today or date.today()
    milestones = _fetch_milestones(fix_version)
    ff = _parse(milestones.get("feature_freeze"))
    cf = _parse(milestones.get("code_freeze"))
    ga = _parse(milestones.get("ga_announce"))
    days_cf = (cf - today).days if cf else None
    phase, label = _current_phase(today, ff, cf, ga)
    warning = _is_warning(today, warning_days, phase=phase, ff=ff, cf=cf)
    return ReleaseContext(
        version=fix_version,
        feature_freeze=ff,
        code_freeze=cf,
        ga_date=ga,
        days_to_code_freeze=days_cf,
        phase=phase,
        phase_label=label,
        freeze_warning=warning,
        today=today,
    )


def _fetch_milestones(version: str) -> dict[str, str]:
    """Parse milestone dates from the RHDHPLAN release Feature ADF description."""
    try:
        from _auth import resolve_jira_auth
        from _jira_client import search_jql

        auth = resolve_jira_auth()
        issues = search_jql(auth, RELEASE_JQL, fields=["summary", "description"])
        if auth.via_acli:
            issues = _enrich_descriptions(auth, issues)
        line = re.match(r"(\d+\.\d+)", version)
        target = line.group(1) if line else version
        for issue in issues:
            summary = (issue.get("fields") or {}).get("summary") or ""
            if target in summary:
                desc = (issue.get("fields") or {}).get("description") or {}
                return extract_milestone_dates(desc)
    except (SystemExit, OSError, RuntimeError) as exc:
        print(f"prepare_refinement: milestones unavailable ({exc})", file=sys.stderr)
    return {}


def _enrich_descriptions(auth, issues: list[dict]) -> list[dict]:
    import json
    import shutil
    import subprocess

    acli = shutil.which("acli")
    if not acli:
        return issues
    out: list[dict] = []
    for issue in issues:
        key = issue.get("key", "")
        if not key:
            out.append(issue)
            continue
        try:
            result = subprocess.run(
                [acli, "jira", "workitem", "view", key, "--fields", "description", "--json"],
                capture_output=True, text=True, timeout=45,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                row = data[0] if isinstance(data, list) else data
                fields = dict(issue.get("fields") or {})
                view_fields = row.get("fields") or {}
                if view_fields.get("description"):
                    fields["description"] = view_fields["description"]
                out.append({**issue, "fields": fields})
            else:
                out.append(issue)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            out.append(issue)
    return out


def _current_phase(
    today: date, ff: date | None, cf: date | None, ga: date | None
) -> tuple[str | None, str | None]:
    ordered: list[tuple[str, str, date]] = []
    if ff:
        ordered.append(("feature_freeze", "Feature Freeze", ff))
    if cf:
        ordered.append(("code_freeze", "Code Freeze", cf))
    if ga:
        ordered.append(("ga_announce", "GA", ga))
    if not ordered:
        return None, None
    if today <= ordered[0][2]:
        return ordered[0][0], ordered[0][1]
    for i in range(len(ordered) - 1):
        if ordered[i][2] < today <= ordered[i + 1][2]:
            return ordered[i + 1][0], ordered[i + 1][1]
    return ordered[-1][0], ordered[-1][1]


def _is_warning(
    today: date, days: int, *, phase: str | None, ff: date | None, cf: date | None
) -> bool:
    if phase == "feature_freeze" and ff:
        return (ff - today).days <= days
    if cf:
        return (cf - today).days <= days
    return False


def _parse(value: str | None) -> date | None:
    if not value or value in ("TBD", "N/A"):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
