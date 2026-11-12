#!/usr/bin/env python3
"""Triage all open overlay repository PRs.

Fetches open PRs, classifies by priority tier, checks staleness,
evaluates assignment status, derives the next PR command from CI state,
and generates a grouped triage report.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

DEFAULT_REPO = "redhat-developer/rhdh-plugin-export-overlays"

# The `publish` commit status is created with the command name as its context.
PUBLISH_CONTEXT = "publish"

STALENESS_THRESHOLDS = {
    "critical": {"warn": 2, "alert": 5},
    "medium": {"warn": 5, "alert": 10},
    "low": {"warn": 14, "alert": 30},
    "skip": {"warn": 999, "alert": 999},
    "unknown": {"warn": 7, "alert": 14},
}

NEXT_ACTION = {
    "draft": "Waiting on author (draft)",
    "multi-workspace": "Split by workspace (/publish is skipped on multi-workspace PRs)",
    "publish-failed": "Read publish run, then /publish or fix-build",
    "publish-missing": "Trigger /publish",
    "publish-pending": "Wait for publish",
    "checks-failed": "Fix failing checks",
    "checks-pending": "Wait for checks",
    "checks-unreadable": "Re-run triage (checks unreadable)",
    "ready": "Ready to merge",
}


def run_gh(args, check=True):
    """Run a gh CLI command and return parsed JSON output."""
    cmd = ["gh"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=60)
        if result.stdout.strip():
            return json.loads(result.stdout)
        return None
    except subprocess.CalledProcessError as exc:
        print(f"Error running: {' '.join(cmd)}", file=sys.stderr)
        print(exc.stderr, file=sys.stderr)
        if check:
            sys.exit(1)
        return None
    except json.JSONDecodeError:
        return None
    except FileNotFoundError:
        print("Error: gh CLI not found. Install from https://cli.github.com/", file=sys.stderr)
        sys.exit(1)


def fetch_open_prs(repo):
    """Fetch all open PRs without the per-PR check and file data."""
    return (
        run_gh(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--limit",
                "100",
                "--json",
                "number,title,labels,assignees,updatedAt,createdAt,author,reviewRequests,isDraft",
            ]
        )
        or []
    )


def fetch_pr_context(repo, number):
    """Fetch the checks and changed files for one PR, or None when unreadable."""
    return run_gh(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "files,statusCheckRollup",
        ],
        check=False,
    )


def classify_priority(labels):
    """Classify PR priority based on labels."""
    names = [lbl["name"] for lbl in labels] if labels else []

    if "do-not-merge" in names:
        return "skip", "⚫ Skip"

    is_mandatory = "mandatory-workspace" in names
    is_update = "workspace-update" in names
    is_addition = "workspace-addition" in names

    if is_mandatory and is_update:
        return "critical", "🔴 Critical"
    if is_mandatory and is_addition:
        return "medium", "🟡 Medium"
    if is_addition:
        return "low", "🟢 Low"
    return "unknown", "❓ Unknown"


def compute_staleness(updated_at, priority_key):
    """Compute days since last update and staleness level."""
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days = (now - updated).days
    except (ValueError, AttributeError):
        days = -1

    thresholds = STALENESS_THRESHOLDS.get(priority_key, STALENESS_THRESHOLDS["unknown"])
    if days >= thresholds["alert"]:
        level = "🚨"
    elif days >= thresholds["warn"]:
        level = "⚠️"
    else:
        level = ""

    return days, level


def assess_assignment(pr):
    """Assess assignment status of a PR."""
    assignees = [a.get("login", "") for a in (pr.get("assignees") or []) if a.get("login")]
    review_requests = pr.get("reviewRequests") or []
    individual_reviewers = [r.get("login", "") for r in review_requests if r.get("login")]
    team_reviewers = [
        r.get("name", "") for r in review_requests if r.get("name") and not r.get("login")
    ]

    if assignees:
        return ", ".join(f"@{u}" for u in assignees), "✅"
    if individual_reviewers:
        return ", ".join(f"@{u}" for u in individual_reviewers) + " (reviewer)", "⚠️"
    if team_reviewers:
        return ", ".join(team_reviewers) + " (team)", "⚠️"
    return "(none)", "❌"


def extract_workspace_from_title(title):
    """Best-effort workspace extraction from PR title."""
    # Titles often follow: "Update <workspace> workspace to ..." or "Add <workspace> workspace"
    lower = title.lower()
    for prefix in ["update ", "add "]:
        if lower.startswith(prefix):
            rest = title[len(prefix) :]
            # Take first word or up to " workspace"
            idx = rest.lower().find(" workspace")
            if idx > 0:
                return rest[:idx].strip()
            parts = rest.split()
            if parts:
                return parts[0].strip()
    # Fallback: first significant word
    return title.split(":")[0].strip() if ":" in title else title[:40]


def extract_workspaces(files):
    """Return the workspace names a PR touches, in first-seen order."""
    names = []
    for entry in files or []:
        match = re.match(r"^workspaces/([^/]+)/", entry.get("path", ""))
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names


def check_entries(pr):
    """Return (name, state, timestamp) for every rollup entry on the PR head."""
    entries = []
    for check in pr.get("statusCheckRollup") or []:
        name = check.get("name") or check.get("context") or ""
        state = (check.get("conclusion") or check.get("state") or "").upper()
        if state in ("", "PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "EXPECTED"):
            state = "pending"
        elif state in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            state = "success"
        elif state in ("CANCELLED", "STALE"):
            state = "cancelled"
        else:
            state = "failed"
        timestamp = (
            check.get("completedAt") or check.get("startedAt") or check.get("createdAt") or ""
        )
        entries.append((name, state, timestamp))
    return entries


def latest_states(entries):
    """Return the newest state per check name, so a re-run does not count twice."""
    newest = {}
    for name, state, timestamp in entries:
        current = newest.get(name)
        # A run still in flight is the current state of that check.
        key = (state == "pending", timestamp)
        if current is None or key >= (current[0] == "pending", current[1]):
            newest[name] = (state, timestamp)
    return {name: state for name, (state, _) in newest.items()}


def evaluate_pr_state(pr):
    """Return (state, workspaces) describing what the PR needs next."""
    labels = [lbl["name"] for lbl in (pr.get("labels") or [])]
    workspaces = extract_workspaces(pr.get("files"))
    latest = latest_states(check_entries(pr))
    publish = latest.get(PUBLISH_CONTEXT, "missing")
    states = list(latest.values())

    if "do-not-merge" in labels:
        return "skip", workspaces
    if pr.get("isDraft"):
        return "draft", workspaces
    # Workspace-scoped commands resolve one workspace and are skipped silently
    # when the PR spans several, so no check can ever appear.
    if len(workspaces) > 1:
        return "multi-workspace", workspaces
    if publish == "cancelled":
        return "publish-missing", workspaces
    if publish in ("failed", "missing", "pending"):
        return f"publish-{publish}", workspaces
    if "failed" in states or "cancelled" in states:
        return "checks-failed", workspaces
    if "pending" in states:
        return "checks-pending", workspaces
    return "ready", workspaces


def suggest_action(pr_info):
    """Suggest action for a PR based on its state."""
    priority = pr_info["priority_key"]
    assignee_status = pr_info["assignee_icon"]
    days = pr_info["days_stale"]

    if priority == "skip":
        return "No action (OCI only)"

    actions = []
    next_action = NEXT_ACTION.get(pr_info["state"])
    if next_action:
        actions.append(next_action)
    if assignee_status == "❌":
        actions.append("Assign owner")
    if days >= STALENESS_THRESHOLDS.get(priority, {}).get("alert", 14):
        actions.append("Escalate (stale)")
    elif days >= STALENESS_THRESHOLDS.get(priority, {}).get("warn", 7):
        actions.append("Ping author")

    if not actions:
        actions.append("Monitor")

    return " + ".join(actions)


def build_triage(repo):
    """Build triage data for all open PRs."""
    prs = fetch_open_prs(repo)

    # The 100-PR list query stays light; checks and files come per PR so the
    # GraphQL call does not time out on a busy repository.
    numbers = [
        pr.get("number") for pr in prs if classify_priority(pr.get("labels") or [])[0] != "skip"
    ]
    with ThreadPoolExecutor(max_workers=6) as pool:
        contexts = dict(
            zip(numbers, pool.map(lambda number: fetch_pr_context(repo, number), numbers))
        )

    categorized = {
        "critical": [],
        "medium": [],
        "low": [],
        "skip": [],
        "unknown": [],
    }

    for pr in prs:
        labels = pr.get("labels") or []
        priority_key, priority_label = classify_priority(labels)
        days, stale_icon = compute_staleness(pr.get("updatedAt", ""), priority_key)
        assignee_display, assignee_icon = assess_assignment(pr)
        plugin = extract_workspace_from_title(pr.get("title", ""))
        author = pr.get("author", {}).get("login", "unknown")
        context = contexts.get(pr.get("number"))
        if priority_key == "skip":
            state, workspaces = "skip", []
        elif context is None:
            state, workspaces = "checks-unreadable", []
        else:
            state, workspaces = evaluate_pr_state({**pr, **context})

        info = {
            "number": pr.get("number"),
            "title": pr.get("title", ""),
            "author": author,
            "priority_key": priority_key,
            "priority_label": priority_label,
            "labels": [lbl["name"] for lbl in labels],
            "plugin": plugin,
            "workspaces": workspaces,
            "state": state,
            "days_stale": days,
            "stale_icon": stale_icon,
            "assignee_display": assignee_display,
            "assignee_icon": assignee_icon,
            "updated_at": pr.get("updatedAt", ""),
            "created_at": pr.get("createdAt", ""),
        }
        info["action"] = suggest_action(info)
        categorized[priority_key].append(info)

    # Sort each tier by staleness descending (most stale first)
    for key in categorized:
        categorized[key].sort(key=lambda x: x["days_stale"], reverse=True)

    return categorized, len(prs)


def format_markdown(categorized, total, repo):
    """Format triage report as markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append("## Overlay PR Triage Report")
    lines.append(f"Generated: {now}")
    lines.append(f"Repository: `{repo}`")
    lines.append(f"Total open PRs: {total}")
    lines.append("")

    # Summary counts
    lines.append("### Summary")
    lines.append(f"- 🔴 Critical: {len(categorized['critical'])}")
    lines.append(f"- 🟡 Medium: {len(categorized['medium'])}")
    lines.append(f"- 🟢 Low: {len(categorized['low'])}")
    lines.append(f"- ⚫ Skip: {len(categorized['skip'])}")
    if categorized["unknown"]:
        lines.append(f"- ❓ Unknown: {len(categorized['unknown'])}")
    lines.append("")

    # Critical
    lines.append("### 🔴 Critical — Mandatory Workspace Updates\n")
    if categorized["critical"]:
        lines.append("| PR | Plugin | Days Stale | Assignee | Action |")
        lines.append("|----|--------|------------|----------|--------|")
        for pr in categorized["critical"]:
            stale_col = (
                f"{pr['stale_icon']} {pr['days_stale']}"
                if pr["stale_icon"]
                else str(pr["days_stale"])
            )
            lines.append(
                f"| #{pr['number']} | {pr['plugin']} | {stale_col} "
                f"| {pr['assignee_icon']} {pr['assignee_display']} | {pr['action']} |"
            )
    else:
        lines.append("No critical PRs. ✅")
    lines.append("")

    # Medium
    lines.append("### 🟡 Medium — Mandatory Workspace Additions\n")
    if categorized["medium"]:
        lines.append("| PR | Plugin | Days Stale | Assignee | Action |")
        lines.append("|----|--------|------------|----------|--------|")
        for pr in categorized["medium"]:
            stale_col = (
                f"{pr['stale_icon']} {pr['days_stale']}"
                if pr["stale_icon"]
                else str(pr["days_stale"])
            )
            lines.append(
                f"| #{pr['number']} | {pr['plugin']} | {stale_col} "
                f"| {pr['assignee_icon']} {pr['assignee_display']} | {pr['action']} |"
            )
    else:
        lines.append("No medium-priority PRs.")
    lines.append("")

    # Low
    lines.append("### 🟢 Low — Community Additions\n")
    if categorized["low"]:
        lines.append("| PR | Plugin | Days Stale | Assignee | Action |")
        lines.append("|----|--------|------------|----------|--------|")
        for pr in categorized["low"]:
            stale_col = (
                f"{pr['stale_icon']} {pr['days_stale']}"
                if pr["stale_icon"]
                else str(pr["days_stale"])
            )
            lines.append(
                f"| #{pr['number']} | {pr['plugin']} | {stale_col} "
                f"| {pr['assignee_icon']} {pr['assignee_display']} | {pr['action']} |"
            )
    else:
        lines.append("No low-priority PRs.")
    lines.append("")

    # Skip
    lines.append("### ⚫ Skipped — Do Not Merge\n")
    if categorized["skip"]:
        lines.append("| PR | Plugin | Reason |")
        lines.append("|----|--------|--------|")
        for pr in categorized["skip"]:
            lines.append(f"| #{pr['number']} | {pr['plugin']} | OCI artifact only |")
    else:
        lines.append("No skipped PRs.")
    lines.append("")

    # Unknown
    if categorized["unknown"]:
        lines.append("### ❓ Unknown — Needs Labels\n")
        lines.append("| PR | Title | Days Stale | Author |")
        lines.append("|----|-------|------------|--------|")
        for pr in categorized["unknown"]:
            lines.append(
                f"| #{pr['number']} | {pr['title'][:50]} | {pr['days_stale']} | @{pr['author']} |"
            )
        lines.append("")

    # Suggested actions
    action_items = []
    for tier in ["critical", "medium", "low"]:
        for pr in categorized[tier]:
            if pr["action"] != "Monitor":
                action_items.append(pr)

    if action_items:
        lines.append("---\n")
        lines.append("## Suggested Actions\n")
        for i, pr in enumerate(action_items, 1):
            lines.append(
                f"{i}. [ ] **{pr['action']}** — PR #{pr['number']} "
                f"({pr['plugin']}, {pr['days_stale']} days stale)"
            )
        lines.append("")

    return "\n".join(lines)


def format_json(categorized, total, repo):
    """Format triage data as JSON."""
    return {
        "repo": repo,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_open": total,
        "summary": {
            "critical": len(categorized["critical"]),
            "medium": len(categorized["medium"]),
            "low": len(categorized["low"]),
            "skip": len(categorized["skip"]),
            "unknown": len(categorized["unknown"]),
        },
        "prs": categorized,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Triage all open overlay repository PRs.",
        epilog="Example: %(prog)s --json",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"GitHub repository (default: {DEFAULT_REPO})",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output structured JSON instead of markdown",
    )
    args = parser.parse_args()

    # Ensure UTF-8 output on Windows (emoji in priority labels)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    categorized, total = build_triage(args.repo)

    if args.json_output:
        print(json.dumps(format_json(categorized, total, args.repo), indent=2))
    else:
        print(format_markdown(categorized, total, args.repo))


if __name__ == "__main__":
    main()
