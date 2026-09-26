#!/usr/bin/env python3
"""RHDH plugin backport automation.

Cherry-picks changes to release branches, creates sequential PRs,
handles Version Packages, updates overlays, and creates changelog PRs.

Branch strategy (by release version):
  < 2.1  — release-x.y/{plugin} (per-plugin maintenance branches)
  >= 2.1 — release-x.y (unified release branch, all workspaces)

Usage:
    python scripts/backport.py 1.10 3456
    python scripts/backport.py 2.1 3456
    python scripts/backport.py 1.10 3456 --mode create
    python scripts/backport.py 1.10 3456 --mode finish
    python scripts/backport.py 1.10 3456 --continue-from /tmp/backport-state-3456.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_REPO = "redhat-developer/rhdh-plugins"
DEFAULT_OVERLAYS_REPO = "redhat-developer/rhdh-plugin-export-overlays"

VP_WORKFLOW_PATH = ".github/workflows/release_workspace_version.yml"
VP_WORKFLOW_FIX_COMMIT = "ef07585"  # rhdh-plugins #4173
VP_WORKFLOW_MARKERS = (
    "release-*/*",
    "version_branch_id",
    "maintenance-changesets-release/${{ version_branch_id }}",
)

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CONFLICT = 2


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def log_step(n: int, title: str) -> None:
    log(f"\n{'=' * 16} Step {n} — {title} {'=' * 16}")


def die(msg: str, code: int = EXIT_FAILURE) -> None:
    log(f"Error: {msg}")
    sys.exit(code)


# ---------------------------------------------------------------------------
# Release version helpers
# ---------------------------------------------------------------------------

UNIFIED_RELEASE_CUTOFF = (2, 1)


def parse_release_version(release: str) -> tuple[int, int]:
    parts = release.strip().split(".")
    if len(parts) < 2:
        die(f"Invalid release version: {release!r} (expected x.y, e.g. 1.10 or 2.1)")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        die(f"Invalid release version: {release!r} (expected x.y, e.g. 1.10 or 2.1)")
    return 0, 0


def uses_unified_release_branch(release: str) -> bool:
    """True for 2.1+ unified release branches (release-x.y)."""
    return parse_release_version(release) >= UNIFIED_RELEASE_CUTOFF


def release_branch_for(release: str, plugin: str) -> str:
    if uses_unified_release_branch(release):
        return f"release-{release}"
    return f"release-{release}/{plugin}"


def vp_changeset_branch_name(
    *,
    unified_release: bool,
    plugin: str,
    release_branch: str,
) -> str:
    """Full VP changesets branch name to check or delete before Version Packages.

    Pre-2.1 per-plugin branches (release_workspace_version.yml / #4173):
      maintenance-changesets-release/release-1.10/orchestrator

    Unified 2.1+ repository-wide branches (rhdh-plugins #4854), per workspace:
      maintenance-changesets-release/release-2.1/lightspeed

    Main's release_workspace.yml uses a different prefix
    (changesets-release/{workspace}/main) and is not used for prior-version backports.
    """
    if unified_release:
        return f"maintenance-changesets-release/{release_branch}/{plugin}"
    return f"maintenance-changesets-release/{release_branch}"


# ---------------------------------------------------------------------------
# Git state helpers — save/restore branch and stash
# ---------------------------------------------------------------------------


def save_git_state() -> tuple[str, bool]:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    original_branch = result.stdout.strip()
    if original_branch == "HEAD":
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        original_branch = result.stdout.strip()

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    had_changes = bool(status.stdout.strip())

    if had_changes:
        log("  Stashing local changes before backport...")
        subprocess.run(
            ["git", "stash", "push", "-u", "-m", "backport-auto: pre-backport stash"],
            capture_output=True,
            text=True,
        )

    return original_branch, had_changes


def restore_git_state(original_branch: str, had_changes: bool) -> None:
    log(f"\n  Restoring original branch: {original_branch}")
    subprocess.run(
        ["git", "checkout", original_branch],
        capture_output=True,
        text=True,
    )
    if had_changes:
        log("  Restoring stashed changes...")
        subprocess.run(
            ["git", "stash", "pop"],
            capture_output=True,
            text=True,
        )


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def run_gh(
    args: list[str],
    *,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    cmd = ["gh"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        die("gh CLI not found. Install from https://cli.github.com/")
    except subprocess.TimeoutExpired:
        die(f"gh command timed out ({timeout}s): {' '.join(cmd)}")
    if check and result.returncode != 0:
        die(f"gh failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result


def run_gh_json(args: list[str], **kwargs) -> dict | list | None:
    result = run_gh(args, **kwargs)
    stdout = result.stdout.strip()
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        die(f"Failed to parse JSON from: {' '.join(['gh'] + args)}\n{stdout[:200]}")
        return None


def run_git(
    args: list[str],
    *,
    check: bool = True,
    cwd: str | Path | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except FileNotFoundError:
        die("git not found.")
    except subprocess.TimeoutExpired:
        die(f"git command timed out ({timeout}s): {' '.join(cmd)}")
    if check and result.returncode != 0:
        die(f"git failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class BackportState:
    release: str = ""
    pr_num: int = 0
    repo: str = DEFAULT_REPO
    overlays_repo: str = DEFAULT_OVERLAYS_REPO
    mode: str = "auto"

    commit_sha: str = ""
    pr_title: str = ""
    pr_url: str = ""
    files: list[str] = field(default_factory=list)

    plugin: str = ""
    release_branch: str = ""
    backport_branch: str = ""
    overlays_branch: str = ""

    conflict_files: list[str] = field(default_factory=list)

    fork_owner: str = ""
    pr1_num: int = 0

    vp_pr_num: int = 0
    vp_commit: str = ""
    vp_version: str = ""

    yarn_lock_only: bool = False
    unified_release: bool = False
    vp_workflow_bootstrapped: bool = False

    overlays_pr_num: int = 0
    changelog_pr_num: int = 0

    completed_steps: list[int] = field(default_factory=list)

    def save(self, path: str | Path) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        log(f"STATE_FILE={path}")

    @classmethod
    def load(cls, path: str | Path) -> BackportState:
        with open(path) as f:
            data = json.load(f)
        state = cls()
        for k, v in data.items():
            if hasattr(state, k):
                setattr(state, k, v)
        return state


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RHDH plugin backport automation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
    %(prog)s 1.10 3456
    %(prog)s 1.10 3456 --mode create
    %(prog)s 1.10 3456 --mode finish
    %(prog)s 1.10 3456 --continue-from /tmp/backport-state-3456.json
""",
    )
    parser.add_argument("release", help="Target release version (e.g. 1.10)")
    parser.add_argument("pr_source", help="PR number, URL, #N, or commit SHA")
    parser.add_argument(
        "--mode",
        choices=["auto", "create", "finish"],
        default="auto",
        help="auto: full workflow, create: steps 1-6, finish: steps 7-10",
    )
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--overlays-repo", default=DEFAULT_OVERLAYS_REPO)
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--continue-from",
        dest="continue_from",
        metavar="STATE_JSON",
        help="Resume after conflict resolution",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip already-backported check",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON output",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# PR source parsing
# ---------------------------------------------------------------------------


def parse_pr_source(pr_source: str) -> tuple[int | None, str | None]:
    if re.fullmatch(r"\d+", pr_source):
        return int(pr_source), None
    m = re.fullmatch(r"#(\d+)", pr_source)
    if m:
        return int(m.group(1)), None
    m = re.search(r"github\.com/[^/]+/[^/]+/pull/(\d+)", pr_source)
    if m:
        return int(m.group(1)), None
    if re.fullmatch(r"[a-f0-9]{7,40}", pr_source):
        return None, pr_source
    die(f"Invalid PR source: {pr_source}\nExpected: PR number, URL, #N, or commit SHA")
    return None, None


# ---------------------------------------------------------------------------
# Step 1 — Fetch PR details
# ---------------------------------------------------------------------------


def step1_fetch_pr(state: BackportState) -> None:
    log_step(1, "Parse arguments and fetch PR details")

    if not state.pr_num and not state.commit_sha:
        die("No PR number or commit SHA available")

    if state.commit_sha and not state.pr_num:
        log(f"Looking up PR for commit {state.commit_sha}...")
        result = run_gh_json(
            [
                "pr",
                "list",
                "--repo",
                state.repo,
                "--search",
                state.commit_sha,
                "--state",
                "merged",
                "--json",
                "number",
                "--jq",
                ".[0].number",
            ],
            check=False,
        )
        if result:
            state.pr_num = int(result) if isinstance(result, (int, float)) else 0

        if not state.pr_num:
            die(f"Could not find merged PR for commit {state.commit_sha}")

    log(f"Fetching PR #{state.pr_num}...")
    pr_data = run_gh_json(
        [
            "pr",
            "view",
            str(state.pr_num),
            "--repo",
            state.repo,
            "--json",
            "files,mergeCommit,title,url,state,baseRefName",
        ]
    )
    if not pr_data:
        die(f"PR #{state.pr_num} not found")

    if pr_data["state"] != "MERGED":
        die(f"PR #{state.pr_num} is not merged (state: {pr_data['state']})")

    if pr_data["baseRefName"] != "main":
        log(f"Warning: PR #{state.pr_num} targets '{pr_data['baseRefName']}', not main")

    state.commit_sha = pr_data["mergeCommit"]["oid"]
    state.pr_title = pr_data["title"]
    state.pr_url = pr_data["url"]
    state.files = [f["path"] for f in pr_data.get("files", [])]

    log(f"  PR: #{state.pr_num} — {state.pr_title}")
    log(f"  Commit: {state.commit_sha[:10]}")
    log(f"  Files: {len(state.files)}")


# ---------------------------------------------------------------------------
# Step 2 — Detect plugin
# ---------------------------------------------------------------------------


def step2_detect_plugin(state: BackportState) -> None:
    log_step(2, "Auto-detect plugin from PR files")

    plugins: set[str] = set()
    for f in state.files:
        parts = f.split("/")
        if len(parts) >= 2 and parts[0] == "workspaces":
            plugins.add(parts[1])

    if not plugins:
        die(
            f"No workspace files found in PR #{state.pr_num}.\nFiles: {', '.join(state.files[:10])}"
        )

    if len(plugins) > 1:
        die(
            f"Multiple plugins detected: {', '.join(sorted(plugins))}\n"
            "Backport each plugin separately."
        )

    state.plugin = plugins.pop()
    state.unified_release = uses_unified_release_branch(state.release)
    state.release_branch = release_branch_for(state.release, state.plugin)
    state.backport_branch = f"backport/{state.pr_num}-to-release-{state.release}"
    state.overlays_branch = f"release-{state.release}"

    log(f"  Plugin: {state.plugin}")
    if state.unified_release:
        log("  Release model: unified (>= 2.1)")
    else:
        log("  Release model: per-plugin (< 2.1)")
    log(f"  Release branch: {state.release_branch}")

    result = run_git(
        ["ls-remote", "--heads", "upstream", f"refs/heads/{state.release_branch}"],
        check=False,
    )
    if not result.stdout.strip():
        if state.unified_release:
            die(
                f"Release branch '{state.release_branch}' does not exist.\n"
                "Unified release branches (2.1+) are created by the release process — "
                f"ensure {state.release_branch} exists before backporting."
            )
        log(
            f"  Release branch '{state.release_branch}' does not exist — creating from latest tag..."
        )
        run_git(["fetch", "upstream", "--tags"])
        tag_result = run_git(
            ["tag", "-l", "@redhat-developer/*@*", "--sort=-v:refname"],
            check=False,
        )
        matching_tag = ""
        for tag in tag_result.stdout.strip().split("\n"):
            if not tag:
                continue
            if f"/{state.plugin}" in tag or state.plugin in tag:
                matching_tag = tag
                break
        if not matching_tag:
            die(
                f"No release tag found for plugin '{state.plugin}'.\n"
                f"Cannot auto-create branch '{state.release_branch}'."
            )
        log(f"  Creating branch from tag: {matching_tag}")
        run_git(["checkout", "-b", state.release_branch, matching_tag])
        run_git(["push", "upstream", state.release_branch])
        log(f"  Branch '{state.release_branch}' created and pushed")

    workspace_files = [f for f in state.files if f.startswith(f"workspaces/{state.plugin}/")]
    if workspace_files and all(f.endswith("yarn.lock") for f in workspace_files):
        state.yarn_lock_only = True
        log("  Detected yarn.lock-only change — will skip Version Packages")


# ---------------------------------------------------------------------------
# Version Packages workflow bootstrap (#4173)
# ---------------------------------------------------------------------------


def fetch_release_branch_workflow(release_branch: str) -> str | None:
    run_git(["fetch", "upstream", release_branch])
    result = run_git(
        ["show", f"upstream/{release_branch}:{VP_WORKFLOW_PATH}"],
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def vp_workflow_supports_release_branches(content: str) -> bool:
    return all(marker in content for marker in VP_WORKFLOW_MARKERS)


def ensure_vp_workflow(state: BackportState) -> None:
    """One-time bootstrap of #4173 workflow changes on per-plugin release branches."""
    if state.yarn_lock_only:
        log("  Yarn.lock-only change — skipping VP workflow check")
        return

    if state.unified_release:
        log(
            "  Unified release branch (2.1+) — VP workflow is release-team owned, "
            "skipping #4173 per-plugin bootstrap"
        )
        return

    log("  Checking Version Packages workflow on release branch...")
    content = fetch_release_branch_workflow(state.release_branch)
    if content and vp_workflow_supports_release_branches(content):
        log("  VP workflow supports release-x.y/{plugin} branches (#4173)")
        return

    log(f"  VP workflow on {state.release_branch} is missing #4173 changes — bootstrapping once...")
    log(
        "  Without this fix, merging a changeset will not open Version Packages "
        "on release-x.y/{plugin} branches."
    )

    run_git(["fetch", "upstream", "main"])
    run_git(["checkout", state.release_branch])

    cherry_pick = run_git(
        ["cherry-pick", VP_WORKFLOW_FIX_COMMIT],
        check=False,
    )
    if cherry_pick.returncode != 0:
        run_git(["cherry-pick", "--abort"], check=False)
        run_git(
            [
                "checkout",
                "upstream/main",
                "--",
                VP_WORKFLOW_PATH,
                "CONTRIBUTING.md",
            ]
        )
        run_git(
            [
                "commit",
                "-m",
                "chore: sync Version Packages workflow for release-x.y branches (#4173)",
            ]
        )

    run_git(["push", "upstream", state.release_branch])
    state.vp_workflow_bootstrapped = True
    log(f"  Bootstrapped VP workflow on {state.release_branch}")


# ---------------------------------------------------------------------------
# Step 3 — Check if already backported
# ---------------------------------------------------------------------------


def step3_check_backported(state: BackportState, *, force: bool = False) -> None:
    log_step(3, "Check if already backported")

    run_git(["fetch", "upstream"])

    result = run_git(
        ["branch", "-r", "--contains", state.commit_sha],
        check=False,
    )
    branches = result.stdout.strip()

    if f"upstream/{state.release_branch}" in branches:
        if force:
            log(
                f"  Warning: {state.commit_sha[:10]} already in {state.release_branch} (--force, continuing)"
            )
        else:
            log(f"  Commit {state.commit_sha[:10]} already exists in {state.release_branch}")
            log("  Nothing to backport. Use --force to override.")
            sys.exit(EXIT_SUCCESS)
        return

    log(f"  Commit {state.commit_sha[:10]} not yet backported — proceeding")


# ---------------------------------------------------------------------------
# Step 4 — Cherry-pick
# ---------------------------------------------------------------------------


def step4_cherry_pick(state: BackportState) -> None:
    log_step(4, "Create local branch and cherry-pick")

    run_git(["fetch", "upstream"])
    run_git(["checkout", "-b", state.backport_branch, f"upstream/{state.release_branch}"])

    result = run_git(
        ["cherry-pick", state.commit_sha],
        check=False,
    )

    if result.returncode != 0:
        conflict_result = run_git(
            ["diff", "--name-only", "--diff-filter=U"],
            check=False,
        )
        state.conflict_files = [f for f in conflict_result.stdout.strip().split("\n") if f]

        state_path = os.path.join(
            tempfile.gettempdir(),
            f"backport-state-{state.pr_num}.json",
        )
        state.save(state_path)

        log("\nCherry-pick conflict detected!")
        log("  Conflicting files:")
        for f in state.conflict_files:
            log(f"    - {f}")
        log("")
        log("Resolve conflicts, then re-run with:")
        log("  git add . && git cherry-pick --continue")
        log(
            f"  python scripts/backport.py {state.release} {state.pr_num} "
            f"--continue-from {state_path}"
        )

        sys.exit(EXIT_CONFLICT)

    log(f"  Cherry-pick successful: {state.commit_sha[:10]}")


def step4_continue(state: BackportState) -> None:
    log_step(4, "Resuming after conflict resolution")

    result = run_git(["branch", "--show-current"], check=False)
    current = result.stdout.strip()
    if current != state.backport_branch:
        log(f"  Switching to {state.backport_branch}...")
        run_git(["checkout", state.backport_branch])

    result = run_git(
        ["grep", "-rlE", r"^<{7}|^={7}|^>{7}", "--", "."],
        check=False,
    )
    if result.stdout.strip():
        die("Conflict markers still present in:\n" + result.stdout.strip())

    log("  No conflict markers found — resuming")


# ---------------------------------------------------------------------------
# Step 5 — Push to fork
# ---------------------------------------------------------------------------


def step5_push_to_fork(state: BackportState) -> None:
    log_step(5, "Push backport branch to fork")

    result = run_gh(["api", "user", "--jq", ".login"])
    state.fork_owner = result.stdout.strip()

    run_git(["push", "origin", state.backport_branch])
    log(f"  Pushed {state.backport_branch} to fork ({state.fork_owner})")


# ---------------------------------------------------------------------------
# Step 6 — Create PR #1 (fork → release branch)
# ---------------------------------------------------------------------------


def step6_create_pr1(state: BackportState, *, merge: bool = True) -> None:
    log_step(6, "Create PR #1 (backport → release)")

    existing = run_gh_json(
        [
            "pr",
            "list",
            "--repo",
            state.repo,
            "--base",
            state.release_branch,
            "--state",
            "open",
            "--json",
            "number,headRefName",
        ]
    )
    if existing:
        for pr in existing:
            if pr.get("headRefName") == state.backport_branch:
                state.pr1_num = pr["number"]
                log(f"  PR #1 already exists: #{state.pr1_num}")
                break

    if not state.pr1_num:
        body = (
            f"Backport of #{state.pr_num} to release-{state.release}\n\n"
            f"**Original PR:** {state.pr_url}\n"
            f"**Plugin:** {state.plugin}\n"
            f"**Release:** {state.release}\n\n"
            f"Cherry-picked commit: `{state.commit_sha[:10]}`\n\n"
            "---\nAuto-generated by backport skill."
        )

        create_result = run_gh(
            [
                "pr",
                "create",
                "--repo",
                state.repo,
                "--base",
                state.release_branch,
                "--head",
                f"{state.fork_owner}:{state.backport_branch}",
                "--title",
                f"backport: #{state.pr_num} to release-{state.release}",
                "--body",
                body,
            ]
        )

        pr_url_match = re.search(r"/pull/(\d+)", create_result.stdout)
        if not pr_url_match:
            die("Failed to get PR #1 number from gh pr create output")
        state.pr1_num = int(pr_url_match.group(1))

        log(f"  PR #1 created: #{state.pr1_num}")

    if merge:
        log("  Monitoring CI...")
        poll_ci(state.pr1_num, state.repo)
        merge_pr(state.pr1_num, state.repo)
        wait_for_merged(state.pr1_num, state.repo)
        log(f"  PR #1 merged: #{state.pr1_num}")


# ---------------------------------------------------------------------------
# CI helpers
# ---------------------------------------------------------------------------


def poll_ci(
    pr_num: int,
    repo: str,
    *,
    timeout: int = 3600,
    interval: int = 30,
) -> None:
    elapsed = 0
    while elapsed < timeout:
        result = run_gh_json(
            [
                "pr",
                "view",
                str(pr_num),
                "--repo",
                repo,
                "--json",
                "statusCheckRollup",
            ]
        )
        checks = result.get("statusCheckRollup", []) if result else []

        if not checks:
            log(f"  No checks yet ({elapsed}s)")
            time.sleep(interval)
            elapsed += interval
            continue

        total = len(checks)
        success = sum(1 for c in checks if c.get("conclusion") == "SUCCESS")
        failure = sum(1 for c in checks if c.get("conclusion") == "FAILURE")
        pending = total - success - failure

        log(f"  Checks: {success}/{total} passed, {pending} pending, {failure} failed")

        if failure > 0:
            failed = [c["name"] for c in checks if c.get("conclusion") == "FAILURE"]
            die(f"CI failed on PR #{pr_num}: {', '.join(failed)}")

        if pending == 0 and success == total:
            log(f"  All {total} checks passed")
            return

        if pending > 0:
            pending_names = [
                c.get("name", "?")
                for c in checks
                if c.get("conclusion") not in ("SUCCESS", "FAILURE")
            ]
            log(f"    Pending: {', '.join(pending_names[:5])}")

        time.sleep(interval)
        elapsed += interval

    die(f"Timeout ({timeout}s) waiting for CI on PR #{pr_num}")


def merge_pr(pr_num: int, repo: str) -> None:
    log(f"  Merging PR #{pr_num}...")
    run_gh(
        [
            "pr",
            "merge",
            str(pr_num),
            "--repo",
            repo,
            "--squash",
            "--auto",
        ]
    )


def wait_for_merged(pr_num: int, repo: str, *, timeout: int = 300) -> None:
    elapsed = 0
    while elapsed < timeout:
        result = run_gh(
            [
                "pr",
                "view",
                str(pr_num),
                "--repo",
                repo,
                "--json",
                "state",
                "--jq",
                ".state",
            ]
        )
        if result.stdout.strip() == "MERGED":
            return
        time.sleep(10)
        elapsed += 10
    die(f"Timeout waiting for PR #{pr_num} to merge")


# ---------------------------------------------------------------------------
# Stale maintenance-changesets-release branch cleanup
# ---------------------------------------------------------------------------


def cleanup_stale_vp_branch(state: BackportState) -> None:
    branch_name = vp_changeset_branch_name(
        unified_release=state.unified_release,
        plugin=state.plugin,
        release_branch=state.release_branch,
    )
    if state.unified_release:
        log(
            f"  Unified release — checking per-workspace VP branch for {state.plugin} "
            f"(same pattern as main)"
        )

    result = run_git(
        ["ls-remote", "--heads", "upstream", f"refs/heads/{branch_name}"],
        check=False,
    )
    if result.stdout.strip():
        log(f"  Stale branch '{branch_name}' found — deleting...")
        run_gh(
            [
                "api",
                "--method",
                "DELETE",
                f"repos/{state.repo}/git/refs/heads/{branch_name}",
            ],
            check=False,
        )
        log(f"  Deleted '{branch_name}'")
    else:
        log(f"  No stale '{branch_name}' branch found")


# ---------------------------------------------------------------------------
# Step 7 — Detect and merge Version Packages PR
# ---------------------------------------------------------------------------


def poll_for_vp_creation(
    plugin: str,
    release_branch: str,
    repo: str,
    *,
    timeout: int = 300,
    interval: int = 10,
) -> int:
    elapsed = 0
    while elapsed < timeout:
        result = run_gh_json(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--base",
                release_branch,
                "--search",
                f"Version Packages ({plugin}) in:title",
                "--state",
                "open",
                "--json",
                "number",
                "--jq",
                ".[0].number",
            ],
            check=False,
        )
        if result and int(result):
            return int(result)
        log(f"  Waiting for Version Packages PR... ({elapsed}s)")
        time.sleep(interval)
        elapsed += interval
    troubleshooting = (
        f"Version Packages PR not created after {timeout}s.\n"
        f"  Release branch: {release_branch}\n"
        "  GitHub runs Prior Version Release Workspace using the workflow file on the "
        "target branch, not main.\n"
    )
    if "/" in release_branch.removeprefix("release-"):
        troubleshooting += (
            f"  Per-plugin branch (< 2.1): verify {VP_WORKFLOW_PATH} includes #4173 "
            f"changes (commit {VP_WORKFLOW_FIX_COMMIT}).\n"
        )
    else:
        troubleshooting += (
            "  Unified branch (2.1+): VP workflow is maintained by the release team — "
            "check Actions for failures on the release branch workflow.\n"
        )
    die(troubleshooting)
    return 0


def poll_for_vp_update(
    vp_pr_num: int,
    before_sha: str,
    repo: str,
    *,
    timeout: int = 300,
    interval: int = 10,
) -> None:
    elapsed = 0
    while elapsed < timeout:
        current_result = run_gh(
            [
                "pr",
                "view",
                str(vp_pr_num),
                "--repo",
                repo,
                "--json",
                "headRefOid",
                "--jq",
                ".headRefOid",
            ]
        )
        if current_result.stdout.strip() != before_sha:
            log(f"  VP PR #{vp_pr_num} updated (new commit)")
            return
        log(f"  Waiting for VP PR update... ({elapsed}s)")
        time.sleep(interval)
        elapsed += interval
    log(f"  Warning: VP PR #{vp_pr_num} not updated within {timeout}s, proceeding anyway")


def extract_version_from_body(body: str) -> str:
    m = re.search(r"@redhat-developer/\S+@([\d.]+)", body)
    return m.group(1) if m else "unknown"


def step7_detect_version_packages(state: BackportState) -> None:
    log_step(7, "Detect and merge Version Packages PR")

    if state.yarn_lock_only:
        log("  Yarn.lock-only change — skipping Version Packages (no npm release needed)")
        run_git(["fetch", "upstream", state.release_branch])
        result = run_git(
            ["rev-parse", f"upstream/{state.release_branch}"],
            check=False,
        )
        state.vp_commit = result.stdout.strip()
        state.vp_version = "n/a (yarn.lock-only)"
        log(f"  Using merge commit as overlay ref: {state.vp_commit[:10]}")
        return

    cleanup_stale_vp_branch(state)

    vp_data = run_gh_json(
        [
            "pr",
            "list",
            "--repo",
            state.repo,
            "--base",
            state.release_branch,
            "--search",
            f"Version Packages ({state.plugin}) in:title",
            "--state",
            "open",
            "--json",
            "number,headRefOid",
            "--jq",
            ".[0]",
        ],
        check=False,
    )

    if vp_data and isinstance(vp_data, dict) and vp_data.get("number"):
        state.vp_pr_num = vp_data["number"]
        before_sha = vp_data.get("headRefOid", "")
        log(f"  Existing VP PR found: #{state.vp_pr_num}")
        if before_sha:
            poll_for_vp_update(state.vp_pr_num, before_sha, state.repo)
    else:
        log("  Waiting for Version Packages PR to be created...")
        time.sleep(10)
        state.vp_pr_num = poll_for_vp_creation(
            state.plugin,
            state.release_branch,
            state.repo,
        )

    log(f"  Version Packages PR: #{state.vp_pr_num}")

    vp_title = run_gh_json(
        [
            "pr",
            "view",
            str(state.vp_pr_num),
            "--repo",
            state.repo,
            "--json",
            "title,baseRefName",
        ]
    )
    if vp_title:
        title = vp_title.get("title", "")
        base = vp_title.get("baseRefName", "")
        if f"Version Packages ({state.plugin})" not in title:
            log(f"  Warning: VP PR title mismatch: {title}")
        if base != state.release_branch:
            die(f"VP PR base is '{base}', expected '{state.release_branch}'")

    log("  Monitoring CI on VP PR...")
    poll_ci(state.vp_pr_num, state.repo)
    merge_pr(state.vp_pr_num, state.repo)
    wait_for_merged(state.vp_pr_num, state.repo)

    vp_merged = run_gh_json(
        [
            "pr",
            "view",
            str(state.vp_pr_num),
            "--repo",
            state.repo,
            "--json",
            "mergeCommit,body",
        ]
    )
    if vp_merged:
        state.vp_commit = vp_merged.get("mergeCommit", {}).get("oid", "")
        state.vp_version = extract_version_from_body(vp_merged.get("body", ""))

    log(f"  VP merged — commit: {state.vp_commit[:10]}, version: {state.vp_version}")


# ---------------------------------------------------------------------------
# Step 8 — Update overlays via GitHub Actions workflow
# ---------------------------------------------------------------------------

OVERLAYS_UPDATE_WORKFLOW = "update-plugins-repo-refs.yaml"


def poll_workflow_run(
    overlays_repo: str,
    workflow_name: str,
    *,
    started_after: str,
    timeout: int = 300,
    interval: int = 15,
) -> dict | None:
    elapsed = 0
    while elapsed < timeout:
        runs = run_gh_json(
            [
                "run",
                "list",
                "--repo",
                overlays_repo,
                "--workflow",
                workflow_name,
                "--limit",
                "5",
                "--json",
                "databaseId,status,conclusion,createdAt",
            ]
        )
        if runs:
            for run in runs:
                if run.get("createdAt", "") >= started_after:
                    status = run.get("status", "")
                    if status == "completed":
                        return run
                    log(f"  Workflow run {run['databaseId']}: {status} ({elapsed}s)")
                    break
        time.sleep(interval)
        elapsed += interval
    return None


def find_overlays_pr(
    overlays_repo: str,
    plugin: str,
    overlays_branch: str,
    *,
    timeout: int = 600,
    interval: int = 20,
) -> int:
    elapsed = 0
    while elapsed < timeout:
        result = run_gh_json(
            [
                "pr",
                "list",
                "--repo",
                overlays_repo,
                "--base",
                overlays_branch,
                "--search",
                f"{plugin} in:title",
                "--state",
                "open",
                "--json",
                "number",
                "--jq",
                ".[0].number",
            ],
            check=False,
        )
        if result and int(result):
            return int(result)
        log(f"  Waiting for overlays PR... ({elapsed}s)")
        time.sleep(interval)
        elapsed += interval
    return 0


def poll_publish_result(
    pr_num: int,
    overlays_repo: str,
    *,
    timeout: int = 900,
    interval: int = 30,
) -> tuple[bool, str]:
    elapsed = 0
    while elapsed < timeout:
        time.sleep(interval)
        elapsed += interval

        result = run_gh_json(
            [
                "pr",
                "view",
                str(pr_num),
                "--repo",
                overlays_repo,
                "--json",
                "comments",
            ]
        )
        if not result or not result.get("comments"):
            continue

        for comment in reversed(result["comments"]):
            body = comment.get("body", "")
            if "publish workflow" not in body.lower():
                continue
            if "completed with failure" in body.lower():
                return False, body
            if "completed with success" in body.lower():
                return True, body
            break

        log(f"  Waiting for /publish result... ({elapsed}s)")

    return False, ""


def step8_update_overlays(state: BackportState) -> None:
    log_step(8, "Update overlays via GitHub Actions workflow")

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    log(f"  Triggering '{OVERLAYS_UPDATE_WORKFLOW}' with single-branch={state.overlays_branch}...")
    run_gh(
        [
            "workflow",
            "run",
            OVERLAYS_UPDATE_WORKFLOW,
            "--repo",
            state.overlays_repo,
            "-f",
            f"single-branch={state.overlays_branch}",
        ]
    )

    log("  Waiting for workflow run to complete...")
    run_result = poll_workflow_run(
        state.overlays_repo,
        OVERLAYS_UPDATE_WORKFLOW,
        started_after=timestamp,
        timeout=600,
    )

    if not run_result:
        log("  Warning: workflow run not found or timed out")
        log("  Checking if overlays PR was created anyway...")
    elif run_result.get("conclusion") != "success":
        log(f"  Warning: workflow run completed with: {run_result.get('conclusion')}")
        log(f"  Run ID: {run_result.get('databaseId')}")

    pr_num = find_overlays_pr(
        state.overlays_repo,
        state.plugin,
        state.overlays_branch,
    )
    if not pr_num:
        die(
            "Overlays PR not found after workflow run.\n"
            f"Check: https://github.com/{state.overlays_repo}/actions/workflows/{OVERLAYS_UPDATE_WORKFLOW}"
        )
    state.overlays_pr_num = pr_num
    log(f"  Overlays PR found: #{state.overlays_pr_num}")

    log("  Adding /ok-to-test label...")
    run_gh(
        [
            "pr",
            "edit",
            str(state.overlays_pr_num),
            "--repo",
            state.overlays_repo,
            "--add-label",
            "ok-to-test",
        ],
        check=False,
    )

    log("  Checking for auto-publish...")
    time.sleep(30)
    publish_ok, publish_output = poll_publish_result(
        state.overlays_pr_num,
        state.overlays_repo,
        timeout=300,
    )

    if not publish_ok and not publish_output:
        log("  Auto-publish not triggered — issuing /publish manually...")
        run_gh(
            [
                "pr",
                "comment",
                str(state.overlays_pr_num),
                "--repo",
                state.overlays_repo,
                "--body",
                "/publish",
            ]
        )
        publish_ok, publish_output = poll_publish_result(
            state.overlays_pr_num,
            state.overlays_repo,
            timeout=900,
        )

    if publish_ok:
        log("  /publish succeeded — waiting for all CI (may take 30+ min)...")
        poll_ci(state.overlays_pr_num, state.overlays_repo, timeout=3600)
        merge_pr(state.overlays_pr_num, state.overlays_repo)
        wait_for_merged(state.overlays_pr_num, state.overlays_repo)
        log(f"  Overlays PR #{state.overlays_pr_num} merged")
    else:
        log(f"  Warning: /publish did not succeed — PR #{state.overlays_pr_num} left open")
        if publish_output:
            log(f"  Publish output: {publish_output[:200]}")
        log("  Manual intervention required")


# ---------------------------------------------------------------------------
# Step 9 — Changelog PR
# ---------------------------------------------------------------------------


def step9_changelog_pr(state: BackportState) -> None:
    log_step(9, "Create changelog PR to main")

    if state.yarn_lock_only:
        log("  Yarn.lock-only change — no version bump, skipping changelog PR")
        return

    if not state.fork_owner:
        result = run_gh(["api", "user", "--jq", ".login"])
        state.fork_owner = result.stdout.strip()

    run_git(["fetch", "upstream"])

    changelog_branch = f"changelog/{state.plugin}-{state.release}-pr{state.pr_num}"
    run_git(["checkout", "-b", changelog_branch, "upstream/main"])

    changelog_file = None
    for candidate in (
        f"workspaces/{state.plugin}/CHANGELOG.md",
        f"workspaces/{state.plugin}/plugins/{state.plugin}/CHANGELOG.md",
    ):
        if Path(candidate).exists():
            changelog_file = candidate
            break

    if not changelog_file:
        log(f"  Warning: CHANGELOG.md not found for {state.plugin}, skipping")
        return

    content = Path(changelog_file).read_text()
    entry = (
        f"\n## {state.vp_version}\n\n"
        f"### Backports\n\n"
        f"- Backported #{state.pr_num}: {state.pr_title} "
        f"([#{state.vp_pr_num}](https://github.com/{state.repo}/pull/{state.vp_pr_num}))\n"
    )

    lines = content.split("\n")
    insert_idx = 0
    heading_count = 0
    for i, line in enumerate(lines):
        if line.startswith("## "):
            heading_count += 1
            if heading_count == 1:
                insert_idx = i
                break
    if insert_idx == 0:
        insert_idx = len(lines)

    lines.insert(insert_idx, entry)
    Path(changelog_file).write_text("\n".join(lines))

    run_git(["add", changelog_file])
    run_git(
        [
            "commit",
            "-m",
            f"docs: add {state.plugin} {state.release} changelog for PR #{state.pr_num}",
        ]
    )
    run_git(["push", "origin", changelog_branch])

    body = (
        f"Adds changelog entry for backported PR #{state.pr_num}\n\n"
        f"**Backport details:**\n"
        f"- Original PR: #{state.pr_num}\n"
        f"- Release: {state.release}\n"
        f"- Version: {state.vp_version}\n"
        f"- Plugin: {state.plugin}\n\n"
        f"This tracks what was backported to the {state.release} release."
    )

    create_result = run_gh(
        [
            "pr",
            "create",
            "--repo",
            state.repo,
            "--base",
            "main",
            "--head",
            f"{state.fork_owner}:{changelog_branch}",
            "--title",
            f"docs: add {state.plugin} {state.release} changelog for backport #{state.pr_num}",
            "--body",
            body,
        ]
    )

    pr_url_match = re.search(r"/pull/(\d+)", create_result.stdout)
    if not pr_url_match:
        die("Failed to get changelog PR number from gh pr create output")
    state.changelog_pr_num = int(pr_url_match.group(1))
    log(f"  Changelog PR created: #{state.changelog_pr_num}")

    log("  Monitoring CI...")
    poll_ci(state.changelog_pr_num, state.repo)
    merge_pr(state.changelog_pr_num, state.repo)
    wait_for_merged(state.changelog_pr_num, state.repo)
    log(f"  Changelog PR #{state.changelog_pr_num} merged")


# ---------------------------------------------------------------------------
# Step 10 — Summary
# ---------------------------------------------------------------------------


def step10_summary(state: BackportState, *, json_output: bool = False) -> None:
    log_step(10, "Summary")

    if json_output:
        result = {
            "plugin": state.plugin,
            "release": state.release,
            "original_pr": state.pr_num,
            "pr1": state.pr1_num,
            "vp_pr": state.vp_pr_num,
            "vp_commit": state.vp_commit,
            "vp_version": state.vp_version,
            "unified_release": state.unified_release,
            "vp_workflow_bootstrapped": state.vp_workflow_bootstrapped,
            "overlays_pr": state.overlays_pr_num,
            "changelog_pr": state.changelog_pr_num,
            "status": "completed",
        }
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        log("")
        log("=" * 40)
        log("BACKPORT COMPLETED SUCCESSFULLY")
        log("=" * 40)
        log("")
        log(f"Plugin: {state.plugin}")
        log(f"Release: {state.release}")
        log(f"Branch model: {'unified' if state.unified_release else 'per-plugin'}")
        log(f"Release branch: {state.release_branch}")
        log(f"Original PR: #{state.pr_num}")
        log("")
        log("All PRs merged:")
        log(f"  1. Backport PR:       #{state.pr1_num}")
        log(f"  2. Version Packages:  #{state.vp_pr_num}")
        log(f"  3. Overlays:          #{state.overlays_pr_num}")
        log(f"  4. Changelog:         #{state.changelog_pr_num}")
        log("")
        log(f"VP commit: {state.vp_commit}")
        log("")
        log("=" * 40)


def print_create_summary(
    state: BackportState,
    *,
    json_output: bool = False,
) -> None:
    if json_output:
        result = {
            "plugin": state.plugin,
            "release": state.release,
            "original_pr": state.pr_num,
            "pr1": state.pr1_num,
            "status": "pr1_created",
        }
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        log("")
        log("=" * 40)
        log("BACKPORT PR CREATED")
        log("=" * 40)
        log("")
        log(f"Plugin: {state.plugin}")
        log(f"Release: {state.release}")
        log(f"Original PR: #{state.pr_num}")
        log("")
        log(f"PR #1: #{state.pr1_num}")
        log(f"  {state.backport_branch} → {state.release_branch}")
        log(f"  https://github.com/{state.repo}/pull/{state.pr1_num}")
        log("")
        log("NEXT STEPS:")
        log(f"  1. Review and merge PR #{state.pr1_num}")
        log(f"  2. Run: python scripts/backport.py {state.release} {state.pr_num} --mode finish")
        log("     (handles Version Packages, overlays, and changelog)")
        log("")
        log("=" * 40)


# ---------------------------------------------------------------------------
# Finish mode prerequisites
# ---------------------------------------------------------------------------


def validate_finish_prerequisites(state: BackportState) -> None:
    run_git(["fetch", "upstream"])
    result = run_git(
        ["branch", "-r", "--contains", state.commit_sha],
        check=False,
    )
    if f"upstream/{state.release_branch}" not in result.stdout:
        log(
            f"  Warning: commit {state.commit_sha[:10]} not found in {state.release_branch}\n"
            f"  Expected: backport-create was run and PRs were merged"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log("=" * 16 + " Using Backport Skill " + "=" * 16)

    original_branch, had_changes = save_git_state()
    log(f"  Saved state: branch={original_branch}, stashed={had_changes}")

    try:
        return _run(args, original_branch, had_changes)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if code != EXIT_CONFLICT:
            restore_git_state(original_branch, had_changes)
        raise
    except Exception:
        restore_git_state(original_branch, had_changes)
        raise


def _run(args, original_branch: str, had_changes: bool) -> int:
    if args.continue_from:
        state = BackportState.load(args.continue_from)
        state.mode = args.mode
        step4_continue(state)
        step5_push_to_fork(state)

        step6_create_pr1(state, merge=(args.mode == "auto"))

        if args.mode == "create":
            restore_git_state(original_branch, had_changes)
            print_create_summary(state, json_output=args.json_output)
            return EXIT_SUCCESS

        step7_detect_version_packages(state)
        step8_update_overlays(state)
        step9_changelog_pr(state)
        restore_git_state(original_branch, had_changes)
        step10_summary(state, json_output=args.json_output)
        return EXIT_SUCCESS

    pr_num, commit_sha = parse_pr_source(args.pr_source)

    state = BackportState(
        release=args.release,
        repo=args.repo,
        overlays_repo=args.overlays_repo,
        mode=args.mode,
    )
    if pr_num:
        state.pr_num = pr_num
    if commit_sha:
        state.commit_sha = commit_sha

    if args.mode in ("auto", "create"):
        step1_fetch_pr(state)
        step2_detect_plugin(state)
        ensure_vp_workflow(state)
        step3_check_backported(state, force=args.force)
        step4_cherry_pick(state)
        step5_push_to_fork(state)

        step6_create_pr1(state, merge=(args.mode == "auto"))

        if args.mode == "create":
            restore_git_state(original_branch, had_changes)
            print_create_summary(state, json_output=args.json_output)
            return EXIT_SUCCESS

    if args.mode == "finish":
        step1_fetch_pr(state)
        step2_detect_plugin(state)
        validate_finish_prerequisites(state)

    step7_detect_version_packages(state)
    step8_update_overlays(state)
    step9_changelog_pr(state)
    restore_git_state(original_branch, had_changes)
    step10_summary(state, json_output=args.json_output)
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
