#!/usr/bin/env python3
"""Fetch refinement data for the agent — queue, milestones, signals.

The agent runs this script, reads the facts JSON, then uses its own
intelligence to produce the facilitator brief.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch RHDH refinement data")
    parser.add_argument("--team", required=True, help="Team name (Install, Plugins, Frontend, AI, COPE, Documentation)")
    parser.add_argument("--fix-version", required=True, help="fixVersion (e.g. 2.1.0)")
    parser.add_argument("--today", help="Override date YYYY-MM-DD (tests)")
    parser.add_argument("--facts-out", type=Path, help="Write facts JSON to file")
    args = parser.parse_args(argv)

    from _auth import resolve_jira_auth
    from _issues import normalize
    from _jira_client import search_jql, child_count
    from _jql import build_queue_jql
    from _release import resolve
    from _team import resolve_team

    today = date.fromisoformat(args.today) if args.today else date.today()
    version = args.fix_version.strip()
    team = resolve_team(args.team)
    release = resolve(version, today=today)

    jql = build_queue_jql(team_id=team["team_id"], fix_versions=(version,))
    auth = resolve_jira_auth()
    raw = search_jql(auth, jql)
    issues = [normalize(r) for r in raw]

    for issue in issues:
        if issue["issuetype"] == "Epic":
            children = child_count(auth, issue["key"])
            if children == 0:
                issue["no_children"] = True
            issue["child_count"] = children

    facts = {
        "team": {
            "name": team["team_name"],
            "board_id": team["board_id"],
            "dashboards": team["dashboards"],
        },
        "release": {
            "version": release.version,
            "feature_freeze": release.feature_freeze.isoformat() if release.feature_freeze else None,
            "code_freeze": release.code_freeze.isoformat() if release.code_freeze else None,
            "ga_date": release.ga_date.isoformat() if release.ga_date else None,
            "days_to_code_freeze": release.days_to_code_freeze,
            "phase": release.phase,
            "phase_label": release.phase_label,
            "freeze_warning": release.freeze_warning,
        },
        "queue": {
            "jql": jql,
            "total": len(issues),
            "issues": issues,
        },
        "today": today.isoformat(),
    }

    output = json.dumps(facts, indent=2) + "\n"

    if args.facts_out:
        args.facts_out.parent.mkdir(parents=True, exist_ok=True)
        args.facts_out.write_text(output)
        print(f"Facts written to {args.facts_out}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
