"""Build a tiny overlay git repo with two branches for --diff tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=diff@test.local",
            "-c",
            "user.name=diff-test",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def init_overlay_git(repo: Path, branches: dict[str, dict[str, str]]) -> Path:
    """Create `repo` with one commit per branch. Keys are git refs (e.g. release-1.9)."""
    repo.mkdir(parents=True, exist_ok=True)
    init = subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if init.returncode != 0:
        raise RuntimeError(
            "git init failed: " + (init.stderr.strip() or init.stdout.strip() or str(init.returncode))
        )
    first = True
    for branch, files in branches.items():
        if first:
            _git(repo, "checkout", "-B", branch)
            first = False
        else:
            _git(repo, "checkout", "-B", branch)
            for child in repo.iterdir():
                if child.name == ".git":
                    continue
                if child.is_dir():
                    _rmtree(child)
                else:
                    child.unlink()
        for rel, content in files.items():
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", branch)
    return repo


def _rmtree(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            _rmtree(child)
        else:
            child.unlink()
    path.rmdir()
