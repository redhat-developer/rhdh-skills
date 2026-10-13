#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""SoS release check-in CLI — timeline-aware checks from references/sos-checks.md."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
_skill_root = _scripts_dir.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

import _release_bridge as bridge_mod  # noqa: E402
import sos_checks as checks_mod  # noqa: E402
import sos_due as due_mod  # noqa: E402
import sos_expect as expect_mod  # noqa: E402
import sos_metrics as metrics_mod  # noqa: E402
import sos_report_format as format_mod  # noqa: E402
import sos_testplan as testplan_mod  # noqa: E402


def _today(as_of: str | None) -> date:
    if as_of:
        return checks_mod._parse_iso(as_of)
    return datetime.now(timezone.utc).date()


def _fetch_milestones(version: str) -> dict[str, str]:
    jql_mod, release_mod, _rf = bridge_mod.import_release_modules()
    release_mod._init_rich_filter()
    active_jql = jql_mod.render("active_release")
    result = release_mod._run(["acli", "jira", "workitem", "search", "--jql", active_jql, "--json"])
    issues = json.loads(result.stdout)

    for issue in issues:
        summary = issue.get("fields", {}).get("summary", "")
        if version not in summary:
            continue
        detail = release_mod._acli_view_json(issue["key"])
        desc_field = detail.get("fields", {}).get("description", {})
        return release_mod._extract_milestone_dates(desc_field)

    raise ValueError(
        f"RHDH {version} is not among active releases from Jira. "
        "Use /rhdh-release-schedule for planned versions."
    )


def _build_jql(query: str, version: str, jql_mod, rf_mod) -> str:
    text = query.strip()
    static_match = re.fullmatch(r'static\s+"([^"]+)"(?:\s+\+\s+(.+))?', text, flags=re.IGNORECASE)
    if static_match:
        fragment = rf_mod.static_filter(static_match.group(1))
        if not fragment:
            raise ValueError(f'Rich Filter static filter not found: "{static_match.group(1)}"')
        extra = (static_match.group(2) or "").strip()
        return jql_mod.compose_fragment(fragment, version=version, extra=extra or None)

    template_match = re.fullmatch(r"template\s+(\S+)", text, flags=re.IGNORECASE)
    if template_match:
        return jql_mod.render(template_match.group(1), version=version)

    queue_match = re.fullmatch(r'queue\s+"([^"]+)"', text, flags=re.IGNORECASE)
    if queue_match:
        fragment = rf_mod.rich_queue(queue_match.group(1))
        if not fragment:
            raise ValueError(f'Rich Filter queue not found: "{queue_match.group(1)}"')
        return jql_mod.compose_fragment(fragment, version=version)

    raise ValueError(
        f'Unsupported query {query!r}. Use static "Name" [+ extra JQL], '
        'template NAME, queue "Name", metric epic_dev_complete static "Name", '
        'due static "Name", expect assignee summary ~ "pattern" [+ extra JQL], '
        'testplan children assigned|signoff open summary ~ "pattern" [+ extra JQL].'
    )


def _check_result_base(row: checks_mod.CheckRow) -> dict:
    """Common metadata copied from a runbook row into a check result."""
    return {
        "id": row.when_raw.lower().replace(" ", "-"),
        "title": row.title,
        "when": row.when_raw,
        "resolved_date": row.resolved_date.isoformat() if row.resolved_date else None,
        "query": row.query,
        "action_item": row.action_item,
    }


def _filter_due_checks(
    due: list[checks_mod.CheckRow],
    *,
    as_of: date,
    milestones: dict[str, str],
) -> list[checks_mod.CheckRow]:
    """Apply metric-specific due windows on top of cumulative selection."""
    filtered: list[checks_mod.CheckRow] = []
    for row in due:
        end_key = due_mod.check_end_milestone_key(row.query)
        if end_key:
            end_raw = milestones.get(end_key, "TBD")
            if end_raw not in ("", "TBD", "N/A") and as_of > checks_mod._parse_iso(end_raw):
                continue
        filtered.append(row)
    return filtered


def _run_due_static_check(
    row: checks_mod.CheckRow,
    version: str,
    release_mod,
    jql_mod,
    rf_mod,
    fmt,
    teams: list[dict],
    milestones: dict[str, str],
) -> dict:
    filter_name = due_mod.due_static_filter_name(row.query)
    milestone_key = due_mod.due_static_milestone_key(row.query)
    if not milestone_key:
        raise ValueError(f'Unsupported due static filter: "{filter_name}"')
    jql = _build_jql(f'static "{filter_name}"', version, jql_mod, rf_mod)
    count, status, error = _count_jql(jql, release_mod, fmt)

    due_date = milestones.get(milestone_key, "TBD")

    return {
        **_check_result_base(row),
        "kind": "due",
        "due_by_milestone": filter_name,
        "due_by_date": due_date,
        "count": count,
        "status": status,
        "error": error,
        "jira_url": jql_mod.jira_url(jql),
        "teams": _run_team_breakdown(jql, teams, release_mod, jql_mod, fmt),
    }


def _run_expect_assignee_check(
    row: checks_mod.CheckRow,
    version: str,
    release_mod,
    jql_mod,
    fmt,
) -> dict:
    pattern, query_extra = expect_mod.parse_expect_assignee_query(row.query)
    jql = expect_mod.build_expect_assignee_jql(pattern, version, jql_mod, extra=query_extra)
    search_url = jql_mod.jira_url(jql)

    try:
        issues = release_mod._acli_json_enriched(
            jql,
            select="key,summary,assignee",
            limit=expect_mod._ASSIGNEE_MATCH_LIMIT,
        )
        evaluation = expect_mod.evaluate_expect_assignee(issues)
        status = "ok"
        error = None
    except Exception as exc:  # noqa: BLE001
        evaluation = {
            "expect_state": "unverified",
            "summary": "Unverified",
            "issue_key": None,
            "issue_url": None,
            "assignee": None,
            "match_count": None,
        }
        status = "unverified"
        error = str(exc)

    jira_url = evaluation.get("issue_url") or search_url

    return {
        **_check_result_base(row),
        "kind": "expect_assignee",
        "summary_pattern": pattern,
        "expect_state": evaluation["expect_state"],
        "summary": evaluation["summary"],
        "issue_key": evaluation.get("issue_key"),
        "issue_url": evaluation.get("issue_url"),
        "assignee": evaluation.get("assignee"),
        "match_count": evaluation.get("match_count"),
        "status": status,
        "error": error,
        "jira_url": jira_url,
        "teams": [],
    }


def _run_testplan_check(
    row: checks_mod.CheckRow,
    version: str,
    release_mod,
    jql_mod,
    fmt,
    milestones: dict[str, str],
) -> dict:
    kind, pattern, query_extra = testplan_mod.parse_testplan_query(row.query)
    epic_jql = testplan_mod.build_testplan_epic_jql(pattern, version, jql_mod, extra=query_extra)
    ff_date = milestones.get("feature_freeze", "TBD")
    result_kind = "testplan_children" if kind == "children assigned" else "testplan_signoff"

    base = {
        **_check_result_base(row),
        "kind": result_kind,
        "summary_pattern": pattern,
        "due_by_milestone": "Feature Freeze",
        "due_by_date": ff_date,
        "teams": [],
    }

    try:
        epics = release_mod._acli_json_enriched(
            epic_jql,
            select="key,summary,status",
            limit=testplan_mod._EPIC_MATCH_LIMIT,
        )
        epic = testplan_mod.resolve_testplan_epic(epics)
        if epic["state"] != "ok":
            return {
                **base,
                "status": "ok",
                "error": None,
                "testplan_state": epic["state"],
                "summary": epic["summary"],
                "epic_key": None,
                "epic_url": None,
                "issue_key": None,
                "issue_url": None,
                "jira_url": jql_mod.jira_url(epic_jql),
                "issues": [],
            }

        epic_key = epic["epic_key"]
        assert epic_key

        if kind == "children assigned":
            child_jql = testplan_mod.children_jql(epic_key)
            children = release_mod._acli_json_enriched(
                child_jql,
                select="key,summary,status,assignee",
                limit=testplan_mod._CHILD_SEARCH_LIMIT,
            )
            evaluation = testplan_mod.evaluate_children_assigned(children)
            if evaluation.get("unassigned_count"):
                jira_url = jql_mod.jira_url(testplan_mod.unassigned_children_jql(epic_key))
                issue_key = None
                issue_url = None
            else:
                jira_url = epic["epic_url"]
                issue_key = epic_key
                issue_url = epic["epic_url"]
            issues = []
        else:
            signoff_jql = testplan_mod.signoff_tasks_jql(epic_key)
            signoff_tasks = release_mod._acli_json_enriched(
                signoff_jql,
                select="key,summary,status,assignee",
                limit=testplan_mod._CHILD_SEARCH_LIMIT,
            )
            evaluation = testplan_mod.evaluate_signoff_open(signoff_tasks)
            jira_url = (
                jql_mod.jira_url(testplan_mod.signoff_open_jql(epic_key))
                if evaluation.get("open_count")
                else epic["epic_url"]
            )
            issue_key = epic_key
            issue_url = epic["epic_url"]
            issues = evaluation.get("issues", [])

        return {
            **base,
            "status": "ok",
            "error": None,
            "testplan_state": evaluation["state"],
            "summary": evaluation["summary"],
            "epic_key": epic_key,
            "epic_url": epic["epic_url"],
            "issue_key": issue_key,
            "issue_url": issue_url,
            "jira_url": jira_url,
            "issues": issues,
            "child_count": evaluation.get("child_count"),
            "unassigned_count": evaluation.get("unassigned_count"),
            "signoff_count": evaluation.get("signoff_count"),
            "open_count": evaluation.get("open_count"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "status": "unverified",
            "error": str(exc),
            "testplan_state": "unverified",
            "summary": "Unverified",
            "epic_key": None,
            "epic_url": None,
            "issue_key": None,
            "issue_url": None,
            "jira_url": jql_mod.jira_url(epic_jql),
            "issues": [],
        }


def _run_ratio_team_breakdown(
    all_jql: str,
    complete_jql: str,
    teams: list[dict],
    release_mod,
    jql_mod,
    fmt,
) -> list[dict]:
    rows = []
    for team in teams:
        cloud_id = team.get("cloud_id", "")
        if not cloud_id:
            continue
        team_all_jql = _team_jql(all_jql, cloud_id)
        team_complete_jql = _team_jql(complete_jql, cloud_id)
        denom, denom_status, denom_error = _count_jql(team_all_jql, release_mod, fmt)
        num, num_status, num_error = _count_jql(team_complete_jql, release_mod, fmt)
        if denom_status == "unverified" or num_status == "unverified":
            status = "unverified"
            error = denom_error or num_error
            numerator = None
            denominator = None
            percent = None
        else:
            status = "ok"
            error = None
            numerator = num or 0
            denominator = denom or 0
            percent = metrics_mod.ratio_percent(numerator, denominator) if denominator else None
        rows.append(
            {
                "team_name": team["team_name"],
                "cloud_id": cloud_id,
                "kind": "ratio",
                "numerator": numerator,
                "denominator": denominator,
                "percent": percent,
                "count": None,
                "status": status,
                "error": error,
                "jira_url": jql_mod.jira_url(team_all_jql),
            }
        )
    return rows


def _run_epic_dev_complete_check(
    row: checks_mod.CheckRow,
    version: str,
    release_mod,
    jql_mod,
    rf_mod,
    fmt,
    teams: list[dict],
) -> dict:
    filter_name = metrics_mod.epic_dev_complete_filter_name(row.query)
    all_jql = metrics_mod.build_epic_dev_complete_jql(
        filter_name, version, jql_mod, rf_mod, dev_complete_only=False
    )
    complete_jql = metrics_mod.build_epic_dev_complete_jql(
        filter_name, version, jql_mod, rf_mod, dev_complete_only=True
    )
    denominator, denom_status, denom_error = _count_jql(all_jql, release_mod, fmt)
    numerator, num_status, num_error = _count_jql(complete_jql, release_mod, fmt)
    if denom_status == "unverified" or num_status == "unverified":
        status = "unverified"
        error = denom_error or num_error
        numerator_value = None
        denominator_value = None
        percent = None
    else:
        status = "ok"
        error = None
        numerator_value = numerator or 0
        denominator_value = denominator or 0
        percent = (
            metrics_mod.ratio_percent(numerator_value, denominator_value)
            if denominator_value
            else None
        )

    return {
        **_check_result_base(row),
        "kind": "ratio",
        "numerator": numerator_value,
        "denominator": denominator_value,
        "percent": percent,
        "count": None,
        "status": status,
        "error": error,
        "jira_url": jql_mod.jira_url(all_jql),
        "jira_url_numerator": jql_mod.jira_url(complete_jql),
        "teams": _run_ratio_team_breakdown(all_jql, complete_jql, teams, release_mod, jql_mod, fmt),
    }


def _team_jql(base_jql: str, cloud_id: str) -> str:
    return f'{base_jql} AND "Team[Team]" = "{cloud_id}"'


def _count_jql(jql: str, release_mod, fmt) -> tuple[int | None, str, str | None]:
    try:
        return release_mod._acli_count(jql, fmt), "ok", None
    except Exception as exc:  # noqa: BLE001
        return None, "unverified", str(exc)


def _run_team_breakdown(
    base_jql: str,
    teams: list[dict],
    release_mod,
    jql_mod,
    fmt,
) -> list[dict]:
    rows = []
    for team in teams:
        cloud_id = team.get("cloud_id", "")
        if not cloud_id:
            continue
        team_jql = _team_jql(base_jql, cloud_id)
        count, status, error = _count_jql(team_jql, release_mod, fmt)
        rows.append(
            {
                "team_name": team["team_name"],
                "cloud_id": cloud_id,
                "count": count,
                "status": status,
                "error": error,
                "jira_url": jql_mod.jira_url(team_jql),
            }
        )
    return rows


def _run_check(
    row: checks_mod.CheckRow,
    version: str,
    release_mod,
    jql_mod,
    rf_mod,
    fmt,
    teams: list[dict],
    milestones: dict[str, str],
) -> dict:
    if metrics_mod.is_epic_dev_complete_query(row.query):
        return _run_epic_dev_complete_check(row, version, release_mod, jql_mod, rf_mod, fmt, teams)
    if due_mod.is_due_static_query(row.query):
        return _run_due_static_check(
            row, version, release_mod, jql_mod, rf_mod, fmt, teams, milestones
        )
    if expect_mod.is_expect_assignee_query(row.query):
        return _run_expect_assignee_check(row, version, release_mod, jql_mod, fmt)
    if testplan_mod.is_testplan_query(row.query):
        return _run_testplan_check(row, version, release_mod, jql_mod, fmt, milestones)

    jql = _build_jql(row.query, version, jql_mod, rf_mod)
    url = jql_mod.jira_url(jql)
    count, status, error = _count_jql(jql, release_mod, fmt)

    return {
        **_check_result_base(row),
        "count": count,
        "status": status,
        "error": error,
        "jira_url": url,
        "teams": _run_team_breakdown(jql, teams, release_mod, jql_mod, fmt),
    }


def _milestone_summary(milestones: dict[str, str], as_of: date) -> list[dict]:
    rows = []
    for key, label in checks_mod._SECTION_ORDER:
        raw = milestones.get(key, "TBD")
        days_until = None
        if raw not in ("", "TBD", "N/A"):
            days_until = (checks_mod._parse_iso(raw) - as_of).days
        rows.append(
            {
                "milestone": label,
                "key": key,
                "date": raw,
                "days_until": days_until,
            }
        )
    return rows


def reports_dir() -> Path:
    """Persistent directory for generated HTML reports."""
    directory = _skill_root / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def build_report(
    version: str,
    *,
    as_of: date | None = None,
    execute: bool = True,
    html_output: str | Path | None = None,
) -> dict:
    as_of = as_of or _today(None)
    jql_mod, release_mod, rf_mod = bridge_mod.import_release_modules()
    from _support import OutputFormatter  # noqa: PLC0415

    release_mod._init_rich_filter()

    milestones = _fetch_milestones(version)
    rows = checks_mod.attach_dates(checks_mod.load_checks(), milestones)
    due, upcoming, active_section = checks_mod.select_checks(
        rows, as_of=as_of, milestones=milestones
    )
    due = _filter_due_checks(due, as_of=as_of, milestones=milestones)

    fmt = OutputFormatter(mode="json")
    teams = release_mod._fetch_teams(category="Engineering") if execute else []
    generated_at = datetime.now(timezone.utc) if execute else None
    executed = []
    if execute:
        for row in due:
            executed.append(
                _run_check(row, version, release_mod, jql_mod, rf_mod, fmt, teams, milestones)
            )

    report = format_mod.enrich_report(
        {
            "version": version,
            "as_of": as_of.isoformat(),
            "generated_at": generated_at.isoformat() if generated_at else None,
            "active_section": {
                "title": active_section.title,
                "milestone_key": active_section.milestone_key,
            },
            "milestones": _milestone_summary(milestones, as_of),
            "checks_due": [
                {
                    "title": row.title,
                    "when": row.when_raw,
                    "resolved_date": row.resolved_date.isoformat() if row.resolved_date else None,
                    "query": row.query,
                    "action_item": row.action_item,
                }
                for row in due
            ],
            "checks_upcoming": [
                {
                    "title": row.title,
                    "when": row.when_raw,
                    "resolved_date": row.resolved_date.isoformat() if row.resolved_date else None,
                    "query": row.query,
                    "action_item": row.action_item,
                }
                for row in upcoming
            ],
            "results": executed,
        }
    )
    if execute:
        output = Path(html_output).expanduser() if html_output else None
        attach_html_artifact(report, output)
    return report


def html_filename_stamp(as_of: str, generated_at: datetime | None = None) -> str:
    """Build a filesystem-safe date-time suffix for HTML report names."""
    when = generated_at or datetime.now(timezone.utc)
    return f"{as_of}-{when.strftime('%H%M%S')}"


def resolve_html_output_path(
    output: Path | None,
    *,
    version: str,
    as_of: str,
    generated_at: datetime | None = None,
) -> Path:
    """Return the HTML output path, adding an as-of date and time suffix when needed."""
    stamp = html_filename_stamp(as_of, generated_at)
    safe_version = version.replace("/", "-")
    if output is None:
        return reports_dir() / f"rhdh-{safe_version}-sos-{stamp}.html"

    suffix = output.suffix or ".html"
    if output.stem.endswith(stamp):
        return output
    return output.with_name(f"{output.stem}-{stamp}{suffix}")


def default_html_path(
    version: str,
    as_of: str,
    generated_at: datetime | None = None,
) -> Path:
    """Default download path for a self-contained HTML report."""
    return resolve_html_output_path(
        None,
        version=version,
        as_of=as_of,
        generated_at=generated_at,
    )


def _report_generated_at(report: dict) -> datetime | None:
    raw = report.get("generated_at")
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def write_report_html(report: dict, output: Path | None = None) -> Path:
    """Write report_html to disk and return the path."""
    if "report_html" not in report:
        raise ValueError("report_html missing; enrich the report before writing HTML")
    path = output or resolve_html_output_path(
        None,
        version=report["version"],
        as_of=report["as_of"],
        generated_at=_report_generated_at(report),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report["report_html"], encoding="utf-8")
    resolved = path.resolve()
    if not resolved.is_file():
        raise RuntimeError(f"HTML report was not written: {resolved}")
    return resolved


def attach_html_artifact(report: dict, output: Path | None = None) -> dict:
    """Write the HTML report and attach report_html_path to the report dict."""
    path = resolve_html_output_path(
        output,
        version=report["version"],
        as_of=report["as_of"],
        generated_at=_report_generated_at(report),
    )
    resolved = write_report_html(report, path)
    report["report_html_path"] = str(resolved)
    return report


def cmd_check(_args: argparse.Namespace) -> None:
    _, release_mod, _rf = bridge_mod.import_release_modules()
    from _support import OutputFormatter  # noqa: PLC0415

    fmt = OutputFormatter(mode="json")
    release_mod._init_rich_filter()
    release_mod.cmd_check(_args, fmt)


def cmd_plan(args: argparse.Namespace) -> None:
    report = build_report(args.version, as_of=_today(args.date), execute=False)
    print(json.dumps({"success": True, "data": report}, indent=2))


def cmd_run(args: argparse.Namespace) -> None:
    report = build_report(
        args.version,
        as_of=_today(args.date),
        execute=True,
        html_output=args.html_output,
    )
    html_path = report["report_html_path"]
    print(json.dumps({"success": True, "data": report}, indent=2))
    print(f"SOS_HTML_REPORT={html_path}", file=sys.stderr)
    if not args.json:
        print()
        print(report["report_markdown"])
        print()
        print(f"HTML report: {html_path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="RHDH SoS release check-in")
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Verify prerequisites")

    plan = sub.add_parser("plan", help="List due and upcoming checks without Jira counts")
    plan.add_argument("version", help="Release version, e.g. 2.1.0")
    plan.add_argument("--date", help="As-of date (YYYY-MM-DD); default is today")

    run = sub.add_parser("run", help="Run due checks and return counts")
    run.add_argument("version", help="Release version, e.g. 2.1.0")
    run.add_argument("--date", help="As-of date (YYYY-MM-DD); default is today")
    run.add_argument(
        "--html-output",
        help=(
            "Write self-contained HTML report; appends {as-of}-{HHMMSS} before .html "
            "(default: reports/rhdh-{version}-sos-{as-of}-{HHMMSS}.html)"
        ),
    )

    args = parser.parse_args(argv)
    handlers = {"check": cmd_check, "plan": cmd_plan, "run": cmd_run}
    handlers[args.command](args)


if __name__ == "__main__":
    main()
