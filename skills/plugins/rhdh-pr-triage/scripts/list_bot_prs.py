#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""List and classify open Renovate and Dependabot PRs across RHDH repositories.

Fetches open PRs authored by bot accounts, classifies each by branch type,
dependency type, CI status, and semver level. Output is consumed by the
triage workflow.

Examples:
    uv run scripts/list_bot_prs.py
    uv run scripts/list_bot_prs.py --repo redhat-developer/rhdh-operator
    uv run scripts/list_bot_prs.py --dry-run
"""

import argparse
import json
import os
import re
import subprocess
import sys

DEFAULT_REPOS = [
    "redhat-developer/rhdh-operator",
    "redhat-developer/rhdh-chart",
    "redhat-developer/rhdh-local",
    "redhat-developer/rhdh-must-gather",
]

BOT_AUTHORS = ["app/renovate", "app/dependabot"]


def log(msg):
    if sys.stderr.isatty() and os.environ.get("NO_COLOR") is None:
        print(msg, file=sys.stderr)


def error_exit(error_key, detail=None):
    result = {"error": error_key}
    if detail:
        result["detail"] = detail
    json.dump(result, sys.stdout, indent=2)
    print()
    sys.exit(1)


def run_gh(args, check=True):
    cmd = ["gh"] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
        )
    except FileNotFoundError:
        error_exit("gh_not_found", "gh CLI is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        error_exit("gh_timeout", f"Command timed out: {' '.join(cmd)}")

    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        error_exit("gh_error", f"{' '.join(cmd)}: {stderr}")

    return result


def run_gh_json(args):
    result = run_gh(args)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        error_exit("gh_json_parse", f"Failed to parse JSON from: {' '.join(['gh'] + args)}")


def classify_branch(base_ref):
    if base_ref == "main" or base_ref == "master":
        return "main"
    if re.match(r"release-\d+\.\d+", base_ref):
        return "release"
    return "other"


def detect_semver_level(title):
    match = re.search(r"(\d+\.\d+\.\d+)\s+to\s+(\d+\.\d+\.\d+)", title, re.IGNORECASE)
    if not match:
        match = re.search(
            r"from\s+v?(\d+\.\d+\.\d+)\s+to\s+v?(\d+\.\d+\.\d+)", title, re.IGNORECASE
        )
    if not match:
        return "unknown"

    from_parts = match.group(1).split(".")
    to_parts = match.group(2).split(".")

    if from_parts[0] != to_parts[0]:
        return "major"
    if from_parts[1] != to_parts[1]:
        return "minor"
    return "patch"


def detect_dep_type(title, files):
    title_lower = title.lower()

    if "go.mod" in title_lower or "golang" in title_lower:
        return "go-module"

    for f in files:
        path = f.get("path", "")
        if path == "go.mod" or path.endswith("/go.mod"):
            return "go-module"

    if "github actions" in title_lower or "actions/" in title_lower:
        return "gh-actions"

    for f in files:
        path = f.get("path", "")
        if path.startswith(".github/workflows/") or path.startswith(".github/actions/"):
            return "gh-actions"

    for f in files:
        path = f.get("path", "")
        if "Chart.yaml" in path or "Chart.lock" in path:
            return "chart-dep"

    return "other"


def detect_go_directives(diff_text):
    go_bumped = False
    toolchain_bumped = False

    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            stripped = line[1:].strip()
            if re.match(r"^go\s+\d+\.\d+", stripped) and not stripped.startswith("golang"):
                go_bumped = True
            if re.match(r"^toolchain\s+go\d+\.\d+", stripped):
                toolchain_bumped = True

    return go_bumped, toolchain_bumped


def detect_chart_folders(files):
    folders = set()
    for f in files:
        path = f.get("path", "")
        match = re.match(r"^charts/([^/]+)/", path)
        if match:
            folders.add(match.group(1))
    return sorted(folders)


def normalize_dep_name(raw):
    name = raw.strip()
    # Renovate prefixes Go modules with "module " — strip it so duplicates match
    # Dependabot's equivalent title: "Bump google.golang.org/grpc from ..."
    name = re.sub(r"^(?:module|digest)\s+", "", name, flags=re.IGNORECASE)
    return name


def extract_dep_name(title):
    match = re.match(
        r"(?:chore\(deps\)|fix\(deps\)|build\(deps\)|chore|fix|build)"
        r"[^:]*:\s*(?:update|bump)\s+(.+?)(?:\s+from\s+|\s+to\s+|\s+digest\s+)",
        title,
        re.IGNORECASE,
    )
    if match:
        return normalize_dep_name(match.group(1))
    match = re.match(r"Bump\s+(.+?)\s+from\s+", title, re.IGNORECASE)
    if match:
        return normalize_dep_name(match.group(1))
    return title


def compute_ci_status(checks, skip_tide=True):
    if not checks:
        return "unknown"

    for check in checks:
        name = check.get("name", "")
        if skip_tide and name == "tide":
            continue
        state = check.get("state", "")
        if state in ("FAILURE", "failure", "ERROR", "error"):
            return "fail"

    for check in checks:
        name = check.get("name", "")
        if skip_tide and name == "tide":
            continue
        state = check.get("state", "")
        if state in ("PENDING", "pending", "IN_PROGRESS", "in_progress", ""):
            return "pending"

    return "pass"


def find_duplicates(prs):
    by_dep = {}
    for pr in prs:
        key = (pr["repo"], pr["base_branch"], pr["dep_name"])
        by_dep.setdefault(key, []).append(pr)

    for group in by_dep.values():
        if len(group) < 2:
            continue
        authors = {p["author"] for p in group}
        if len(authors) < 2:
            continue
        renovate = [p for p in group if "renovate" in p["author"]]
        dependabot = [p for p in group if "dependabot" in p["author"]]
        if renovate and dependabot:
            for d in dependabot:
                d["duplicate_of"] = renovate[0]["number"]


def fetch_prs_for_repo(repo):
    log(f"Fetching bot PRs from {repo}...")
    prs = []
    for author in BOT_AUTHORS:
        raw = run_gh_json(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--author",
                author,
                "--state",
                "open",
                "--limit",
                "100",
                "--json",
                "number,title,baseRefName,headRefName,author,labels,isDraft,mergeable,files,url",
            ]
        )
        for pr_data in raw:
            labels = [label.get("name", "") for label in pr_data.get("labels", [])]
            files = pr_data.get("files", [])
            title = pr_data.get("title", "")
            author_login = pr_data.get("author", {}).get("login", "")
            base_ref = pr_data.get("baseRefName", "")
            number = pr_data.get("number", 0)
            is_conflicted = pr_data.get("mergeable", "") == "CONFLICTING"

            dep_type = detect_dep_type(title, files)
            dep_name = extract_dep_name(title)
            semver_level = detect_semver_level(title)
            chart_folders = detect_chart_folders(files) if repo.endswith("/rhdh-chart") else []

            go_directive_bumped = False
            go_toolchain_bumped = False
            if dep_type == "go-module" and repo.endswith("/rhdh-operator"):
                log(f"  Checking Go directives for #{number}...")
                diff_result = run_gh(
                    ["pr", "diff", str(number), "--repo", repo],
                    check=False,
                )
                if diff_result.returncode == 0:
                    go_directive_bumped, go_toolchain_bumped = detect_go_directives(
                        diff_result.stdout
                    )

            log(f"  Checking CI for #{number}...")
            checks_raw = run_gh(
                [
                    "pr",
                    "checks",
                    str(number),
                    "--repo",
                    repo,
                    "--json",
                    "name,state",
                ],
                check=False,
            )
            checks = []
            if checks_raw.returncode == 0 and checks_raw.stdout.strip():
                try:
                    checks = json.loads(checks_raw.stdout)
                except json.JSONDecodeError:
                    pass
            ci_status = compute_ci_status(checks)

            prs.append(
                {
                    "repo": repo,
                    "number": number,
                    "url": pr_data.get("url", ""),
                    "title": title,
                    "base_branch": base_ref,
                    "branch_type": classify_branch(base_ref),
                    "author": author_login,
                    "labels": labels,
                    "ci_status": ci_status,
                    "is_draft": pr_data.get("isDraft", False),
                    "is_conflicted": is_conflicted,
                    "dep_type": dep_type,
                    "dep_name": dep_name,
                    "semver_level": semver_level,
                    "go_directive_bumped": go_directive_bumped,
                    "go_toolchain_bumped": go_toolchain_bumped,
                    "chart_folders": chart_folders,
                    "duplicate_of": None,
                }
            )
    return prs


def main():
    parser = argparse.ArgumentParser(
        description="List and classify open Renovate and Dependabot PRs across RHDH repos."
    )
    parser.add_argument(
        "--repo",
        help="Restrict to a single repository (owner/repo).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mark the output as a dry run (no mutations will be executed).",
    )
    args = parser.parse_args()

    repos = [args.repo] if args.repo else DEFAULT_REPOS

    all_prs = []
    for repo in repos:
        all_prs.extend(fetch_prs_for_repo(repo))

    find_duplicates(all_prs)
    all_prs.sort(key=lambda pr: pr["number"], reverse=True)

    output = {
        "dry_run": args.dry_run,
        "prs": all_prs,
    }

    if sys.stdout.isatty():
        json.dump(output, sys.stdout, indent=2)
    else:
        json.dump(output, sys.stdout)
    print()

    log(f"Done. {len(all_prs)} bot PR(s) found across {len(repos)} repo(s).")


if __name__ == "__main__":
    main()
