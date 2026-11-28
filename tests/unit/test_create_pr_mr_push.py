"""create-pr-mr.sh push behavior against local bare remotes.

Regression tests for RHIDP-18799: a bare --force-with-lease cannot resolve the
tracking ref in a single-branch clone (its configured fetch refspec covers only
the base branch), so replacing a stale bot branch tip was rejected with
"(stale info)" and the PR/MR never opened.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from conftest import git_env

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREATE_PR_MR = PROJECT_ROOT / "skills" / "ci" / "rhdh-pr-mr" / "scripts" / "create-pr-mr.sh"

TOPIC = "chore/automated-yarn-bump"

FAKE_GH = """#!/usr/bin/env bash
case "$1" in
  pr)
    case "$2" in
      list) ;; # no open PRs: empty output, as gh -q '.[0].url // empty' would give
      create) echo "https://github.com/example/repo/pull/1" ;;
      *) exit 0 ;;
    esac
    ;;
  *) exit 0 ;;
esac
"""


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
        env=git_env(),
    )


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message + "\n\nAssisted-By: pytest")


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-b", "main", check=False)
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    return path


def _make_origin_with_stale_topic(tmp_path: Path) -> Path:
    """Bare remote with main plus a stale, conflicting bot topic branch."""
    seed = _init_repo(tmp_path / "seed")
    origin = tmp_path / "origin.git"
    (seed / "f.txt").write_text("base")
    _commit_all(seed, "base")
    _git(seed, "branch", "-M", "main")
    _git(seed, "checkout", "-b", TOPIC)
    (seed / "f.txt").write_text("old bot bump")
    _commit_all(seed, "old bot bump")
    _git(seed, "checkout", "main")
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(seed), str(origin)],
        check=True,
        capture_output=True,
        env=git_env(),
    )
    return origin


def _single_branch_clone(origin: Path, tmp_path: Path) -> Path:
    """Clone the way yarn-bump.sh does: single-branch, shallow, base only."""
    work = tmp_path / "work"
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--branch",
            "main",
            "--single-branch",
            "--depth",
            "5",
            str(origin),
            str(work),
        ],
        check=True,
        capture_output=True,
        env=git_env(),
    )
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")
    return work


def _run_create_pr_mr(work: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(FAKE_GH)
    fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IEXEC)
    env = git_env(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    env.pop("GITLAB_PIPELINE", None)
    return subprocess.run(
        [
            str(CREATE_PR_MR),
            "--cwd",
            str(work),
            "--base",
            "main",
            "--head",
            TOPIC,
            "--title",
            "chore: bump thing",
            "--body",
            "body",
            "--attribution",
            "pytest",
            "--no-open",
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def test_stale_topic_tip_is_replaced_from_single_branch_clone(tmp_path: Path) -> None:
    """A conflicted stale bot tip must be force-replaced, not rejected (stale info)."""
    origin = _make_origin_with_stale_topic(tmp_path)
    work = _single_branch_clone(origin, tmp_path)
    (work / "f.txt").write_text("new bot bump")  # conflicts with the stale tip
    _commit_all(work, "new bot bump")

    result = _run_create_pr_mr(work, tmp_path)

    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    local_tip = _git(work, "rev-parse", "HEAD").stdout.strip()
    remote_tip = _git(work, "ls-remote", origin, f"refs/heads/{TOPIC}").stdout.split()[0]
    assert local_tip == remote_tip


def test_new_topic_branch_is_created_without_a_lease(tmp_path: Path) -> None:
    """No remote topic branch: the push is a plain create and succeeds."""
    seed = _init_repo(tmp_path / "seed")
    origin = tmp_path / "origin.git"
    (seed / "f.txt").write_text("base")
    _commit_all(seed, "base")
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(seed), str(origin)],
        check=True,
        capture_output=True,
        env=git_env(),
    )
    work = _single_branch_clone(origin, tmp_path)
    (work / "g.txt").write_text("new")
    _commit_all(work, "new commit")

    result = _run_create_pr_mr(work, tmp_path)

    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    remote_refs = _git(work, "ls-remote", origin, f"refs/heads/{TOPIC}").stdout
    assert remote_refs.strip(), "topic branch was not created on the remote"
