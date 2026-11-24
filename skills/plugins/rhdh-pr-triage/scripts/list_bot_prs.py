#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""List and classify open Renovate and Dependabot PRs across RHDH repositories.

Fetches open PRs authored by bot accounts, classifies each by branch type,
dependency type, CI status, semver level, and go.mod directive changes (with
the `godebug` pin in effect on the base branch). Output is consumed by the
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

# Root files that mark a branch as a Go codebase, in the order they are probed.
GO_MARKERS = ["go.mod", "go.work"]

DIRECTIVE_PATTERNS = {
    "go": re.compile(r"^go\s+(\d+\.\d+(?:\.\d+)?)$"),
    "toolchain": re.compile(r"^toolchain\s+(go\d+\.\d+(?:\.\d+)?)$"),
    "godebug": re.compile(r"^godebug\s+(.+)$"),
}

SECURITY_LABEL = "kind/security"


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


DEV_BRANCH_REPOS = {
    "redhat-developer/rhdh-local": "dev",
}


def classify_branch(base_ref, repo=""):
    if base_ref == "main" or base_ref == "master":
        return "main"
    if base_ref == DEV_BRANCH_REPOS.get(repo):
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


def _directive_values(diff_text):
    """Collect go.mod directive values from the added and removed diff lines."""
    added = {}
    removed = {}
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if len(line) < 2 or line[0] not in "+-":
            continue
        bucket = added if line[0] == "+" else removed
        stripped = line[1:].strip()
        for name, pattern in DIRECTIVE_PATTERNS.items():
            match = pattern.match(stripped)
            if match:
                bucket[name] = match.group(1).strip()
    return added, removed


def detect_go_directives(diff_text):
    """Return the go.mod directive changes a PR makes, as a flat dict.

    A directive counts as changed only when the added value differs from the
    removed one, so a diff that touches unrelated lines leaves it False. A
    removed `godebug` line yields `go_godebug_changed` with no value.
    """
    added, removed = _directive_values(diff_text)

    def changed(name):
        return (name in added or name in removed) and added.get(name) != removed.get(name)

    return {
        "go_directive_bumped": changed("go"),
        "go_toolchain_bumped": changed("toolchain"),
        "go_godebug_changed": changed("godebug"),
        "go_directive_value": added.get("go"),
        "go_godebug_value": added.get("godebug"),
    }


def parse_gomod_directives(gomod_text):
    """Return the go, toolchain and godebug directive values from a go.mod file."""
    values = {"go": None, "toolchain": None, "godebug": None}
    for line in gomod_text.splitlines():
        stripped = line.split("//")[0].strip()
        for name, pattern in DIRECTIVE_PATTERNS.items():
            match = pattern.match(stripped)
            if match:
                values[name] = match.group(1).strip()
    return values


def is_security_pr(labels, title):
    """Whether a PR carries a security marker in its own labels or title.

    Renovate labels vulnerability PRs `kind/security` and appends `[security]` to
    the title. dependabot-core emits a `[security]` title prefix too, but not
    every Dependabot deployment uses that renderer — so this is only one half of
    the signal; `security_from_alerts` supplies the other.
    """
    if SECURITY_LABEL in labels:
        return True
    return "[security]" in title.lower()


def fetch_open_alerts(repo, cache):
    """Map open Dependabot alert package names to their first patched version.

    Returns None when the alerts endpoint is unreadable — alerts disabled for the
    repository, or a token without the scope — because that means "no alert
    signal", not "no vulnerability", and it must not abort a run over a
    repository that publishes no alerts.
    """
    key = ("alerts", repo)
    if key in cache:
        return cache[key]

    result = run_gh(
        [
            "api",
            f"repos/{repo}/dependabot/alerts?state=open&per_page=100",
            "--paginate",
            "--jq",
            ".[] | {pkg: .dependency.package.name,"
            " patched: .security_vulnerability.first_patched_version.identifier}",
        ],
        check=False,
    )
    if result.returncode != 0:
        cache[key] = None
        return None

    alerts = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        package = (entry.get("pkg") or "").strip().lower()
        if package:
            alerts[package] = entry.get("patched")
    cache[key] = alerts
    return alerts


def extract_target_version(title):
    """The version a bot PR moves a dependency to, when the title names one."""
    match = re.search(r"\bto\s+v?(\d+(?:\.\d+)*)", title, re.IGNORECASE)
    return match.group(1) if match else None


def parse_version(text):
    """Numeric components of a version string, padded so tuples compare.

    A string that is not a plain version yields None rather than a partial
    number, so a title fragment cannot be mistaken for a version below the fix.
    """
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    if not match:
        return None
    return [int(part) for part in match.group(1).split(".")]


def version_at_least(candidate, floor):
    """Whether `candidate` is `floor` or newer, padding the shorter tuple with 0."""
    left = parse_version(candidate)
    right = parse_version(floor)
    if not left or not right:
        return None
    width = max(len(left), len(right))
    left += [0] * (width - len(left))
    right += [0] * (width - len(right))
    return left >= right


def security_from_alerts(alerts, dep_name, target_version=None):
    """Whether an open alert covers the package a PR bumps.

    Dependabot security updates, and Renovate's vulnerability PRs, are created
    from these alerts, so the alert is what makes the PR a security fix
    regardless of how the bot renders its title. A bump that stops short of the
    alert's first patched version is not a fix, which keeps an ordinary version
    update of a flagged package from borrowing the security exception.
    """
    if not alerts:
        return False
    package = dep_name.strip().lower()
    if package not in alerts:
        return False

    patched = alerts[package]
    if patched and version_at_least(target_version, patched) is False:
        return False
    return True


def fetch_branch_file(repo, path, ref, cache):
    """Fetch a file from a branch, or None when the path is not there.

    A 404 means the branch genuinely lacks the file. Any other failure aborts the
    run instead of returning None, because "absent" drives a policy decision
    here: a transient error must not quietly switch the Go checks off for a Go
    repository. Results are cached per repository, path and ref — a batch usually
    holds several PRs against the same base branch.
    """
    key = (repo, path, ref)
    if key in cache:
        return cache[key]

    result = run_gh(
        [
            "api",
            f"repos/{repo}/contents/{path}?ref={ref}",
            "-H",
            "Accept: application/vnd.github.raw",
        ],
        check=False,
    )

    if result.returncode == 0:
        text = result.stdout
    elif "404" in result.stderr or "Not Found" in result.stderr:
        text = None
    else:
        error_exit(
            "gh_error",
            f"repos/{repo}/contents/{path}?ref={ref}: {result.stderr.strip()}",
        )

    cache[key] = text
    return text


def is_go_repo(repo, branch, cache):
    """Whether a branch roots a Go codebase, judged from its own files.

    Discovering this beats a hardcoded repository list: the list goes stale when
    a repository gains or drops Go, and a chart or local-environment PR whose
    title mentions a Go module is classified `go-module` without shipping any Go
    at all.
    """
    return any(fetch_branch_file(repo, marker, branch, cache) is not None for marker in GO_MARKERS)


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
    file_cache = {}
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

            # Security PRs get the release-branch exceptions, so the signal has
            # to be right. Labels and titles cover Renovate; the open alert set
            # covers GitHub-hosted Dependabot, which marks nothing in the title.
            is_security = is_security_pr(labels, title)
            if not is_security:
                is_security = security_from_alerts(
                    fetch_open_alerts(repo, file_cache),
                    dep_name,
                    extract_target_version(title),
                )

            go_directives = {
                "go_directive_bumped": False,
                "go_toolchain_bumped": False,
                "go_godebug_changed": False,
                "go_directive_value": None,
                "go_godebug_value": None,
            }
            base_godebug_pin = None

            if dep_type == "go-module" and is_go_repo(repo, base_ref, file_cache):
                log(f"  Checking Go directives for #{number}...")
                diff_result = run_gh(
                    ["pr", "diff", str(number), "--repo", repo],
                    check=False,
                )
                if diff_result.returncode == 0:
                    go_directives = detect_go_directives(diff_result.stdout)

                # The pin a Go release branch inherits at branch cut is what
                # bounds a security-driven directive bump, and the only rule that
                # reads it is gated on the security signal: for an ordinary
                # dependency update the directive is frozen and the PR closes
                # before the pin matters. Read it only where it decides
                # something.
                if go_directives["go_directive_bumped"] and is_security:
                    gomod = fetch_branch_file(repo, "go.mod", base_ref, file_cache)
                    if gomod:
                        base_godebug_pin = parse_gomod_directives(gomod)["godebug"]

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
                    "branch_type": classify_branch(base_ref, repo),
                    "author": author_login,
                    "labels": labels,
                    "is_security": is_security,
                    "ci_status": ci_status,
                    "is_draft": pr_data.get("isDraft", False),
                    "is_conflicted": is_conflicted,
                    "dep_type": dep_type,
                    "dep_name": dep_name,
                    "semver_level": semver_level,
                    **go_directives,
                    "base_godebug_pin": base_godebug_pin,
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
