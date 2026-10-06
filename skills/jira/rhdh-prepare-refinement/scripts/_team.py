"""Team registry — resolved at runtime from Jira board names."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

JIRA_BASE = "https://redhat.atlassian.net"

# Known boards from /rhdh-jira-api references/jql-patterns.md
KNOWN_BOARDS: dict[str, int] = {
    "install": 11462,
    "plugins": 11549,
    "frontend": 11525,
    "ai": 10725,
    "cope": 11374,
    "documentation": 10851,
}

# Dashboards are Install-specific for now; other teams can add theirs.
DASHBOARDS: dict[str, dict[str, dict[str, str]]] = {
    "install": {
        "feature_tracking": {"url": f"{JIRA_BASE}/jira/dashboards/17955", "label": "View all features this release"},
        "team_refinement": {"url": f"{JIRA_BASE}/jira/dashboards/22332", "label": "View issues for refinement"},
        "hygiene": {"url": f"{JIRA_BASE}/jira/dashboards/23962", "label": "View issues needing hygiene"},
    },
}

DEFAULT_DASHBOARDS: dict[str, dict[str, str]] = {
    "feature_tracking": {"url": JIRA_BASE, "label": "View features in Jira"},
    "team_refinement": {"url": JIRA_BASE, "label": "View queue in Jira"},
    "hygiene": {"url": JIRA_BASE, "label": "View hygiene in Jira"},
}


def resolve_team(name: str) -> dict:
    """Return team_id, board_id, team_name, dashboards for a team name."""
    key = name.strip().lower()
    board_id = KNOWN_BOARDS.get(key)
    if not board_id:
        raise SystemExit(
            f"Unknown team '{name}'. Known teams: {', '.join(KNOWN_BOARDS.keys())}"
        )
    team_id = _discover_team_id(board_id)
    display = name.strip().title()
    dashboards = DASHBOARDS.get(key, DEFAULT_DASHBOARDS)
    return {
        "team_id": team_id,
        "board_id": board_id,
        "team_name": display,
        "dashboards": dashboards,
    }


def _discover_team_id(board_id: int) -> str:
    """Get the team UUID from the board's active sprint issues."""
    acli = shutil.which("acli")
    if not acli:
        raise SystemExit("acli not found — needed to resolve team ID from board")
    try:
        result = subprocess.run(
            [acli, "jira", "board", "list-sprints", "--id", str(board_id),
             "--state", "active", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise SystemExit(f"Could not list sprints for board {board_id}: {result.stderr}")
        sprints = json.loads(result.stdout)
        if isinstance(sprints, dict):
            sprints = sprints.get("values", sprints.get("sprints", []))
        if not sprints:
            raise SystemExit(f"No active sprint on board {board_id}")
        sprint_id = sprints[0].get("id") or sprints[0].get("sprintId")

        result = subprocess.run(
            [acli, "jira", "sprint", "list-workitems", "--sprint", str(sprint_id),
             "--board", str(board_id), "--limit", "1", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise SystemExit(f"Could not list sprint items: {result.stderr}")
        items = json.loads(result.stdout)
        if isinstance(items, dict):
            items = items.get("issues", items.get("values", []))
        if not items:
            raise SystemExit(f"Active sprint on board {board_id} is empty")
        key = items[0].get("key", "")

        result = subprocess.run(
            [acli, "jira", "workitem", "view", key, "--fields", "*all", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        row = data[0] if isinstance(data, list) else data
        team_field = (row.get("fields") or {}).get("customfield_10001") or {}
        team_id = team_field.get("id", "")
        if not team_id:
            raise SystemExit(f"Could not extract team ID from {key}")
        return team_id
    except (json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"Team ID discovery failed: {exc}") from exc
