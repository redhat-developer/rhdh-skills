"""Locate, clone, or git-show rhdh-plugin-export-overlays without checking out.

Shared by product-catalog scripts. Sparse clone includes both
workspaces/*/metadata and catalog-entities/extensions/plugins.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

OVERLAYS_GIT = "https://github.com/redhat-developer/rhdh-plugin-export-overlays.git"
OVERLAYS_DIRNAME = "rhdh-plugin-export-overlays"
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.\d+)?$")
SPARSE_PATTERNS = (
    "workspaces/*/metadata",
    "workspaces/*/metadata/*",
    "catalog-entities/extensions/plugins",
    "catalog-entities/extensions/plugins/*",
    "default.packages.yaml",
)

LoadWorkdir = Callable[[Path], list[dict[str, Any]]]
LoadGit = Callable[[Path, str], tuple[list[dict[str, Any]], str]]


def version_to_ref(version: str) -> str:
    v = version.strip()
    if not v:
        raise ValueError("version is empty")
    lower = v.lower()
    if lower in {"main", "next", "unreleased", "latest"}:
        return "main"
    match = VERSION_RE.match(v)
    if match:
        return f"release-{match.group(1)}.{match.group(2)}"
    return v


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def git_ref_exists(repo: Path, ref: str) -> str | None:
    for candidate in (ref, f"origin/{ref}", f"refs/remotes/origin/{ref}"):
        proc = git(repo, "rev-parse", "--verify", "--quiet", candidate, check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return candidate
    return None


def ensure_git_ref(repo: Path, ref: str) -> str:
    existing = git_ref_exists(repo, ref)
    if existing:
        return existing
    # Single-branch clones (--branch) only fetch that one heads refspec.
    # Name the dest so git_ref_exists can see the second version.
    dest = f"refs/remotes/origin/{ref.removeprefix('origin/')}"
    specs = (
        f"+{ref}:{dest}",
        f"+refs/heads/{ref}:{dest}",
        f"+refs/tags/{ref}:refs/tags/{ref}",
    )
    errors: list[str] = []
    for spec in specs:
        fetch = git(repo, "fetch", "--depth", "1", "origin", spec, check=False)
        if fetch.returncode != 0:
            errors.append(fetch.stderr.strip() or fetch.stdout.strip() or spec)
            continue
        existing = git_ref_exists(repo, ref)
        if existing:
            return existing
        dest_ok = git(repo, "rev-parse", "--verify", "--quiet", dest, check=False)
        if dest_ok.returncode == 0 and dest_ok.stdout.strip():
            return dest
        tag = f"refs/tags/{ref}"
        tag_ok = git(repo, "rev-parse", "--verify", "--quiet", tag, check=False)
        if tag_ok.returncode == 0 and tag_ok.stdout.strip():
            return tag
    detail = "; ".join(e for e in errors if e) or "no matching ref"
    raise FileNotFoundError(f"Cannot resolve git ref {ref!r} in {repo}: {detail}")


def read_via_git(repo: Path, resolved_ref: str, rel_path: str) -> str:
    return git(repo, "show", f"{resolved_ref}:{rel_path}").stdout


def list_via_git(repo: Path, resolved_ref: str, *tree_paths: str) -> list[str]:
    if not tree_paths:
        tree_paths = (".",)
    proc = git(repo, "ls-tree", "-r", "--name-only", resolved_ref, "--", *tree_paths)
    return proc.stdout.splitlines()


def parse_cat_file_batch(stdout: bytes, rel_paths: list[str]) -> dict[str, str]:
    """Map requested paths to blob text from `git cat-file --batch` output."""
    texts: dict[str, str] = {}
    offset = 0
    n = len(stdout)
    for path in rel_paths:
        nl = stdout.find(b"\n", offset)
        if nl < 0:
            break
        header = stdout[offset:nl]
        offset = nl + 1
        if header.endswith(b" missing") or header.endswith(b" ambiguous"):
            continue
        parts = header.split()
        if len(parts) < 3:
            continue
        try:
            size = int(parts[-1])
        except ValueError:
            continue
        content = stdout[offset : offset + size]
        offset += size
        if offset < n and stdout[offset : offset + 1] == b"\n":
            offset += 1
        texts[path] = content.decode("utf-8", errors="replace")
    return texts


def read_files_via_git(repo: Path, resolved_ref: str, rel_paths: list[str]) -> dict[str, str]:
    """Read many blobs in one `git cat-file --batch` (one process, batched fetch)."""
    if not rel_paths:
        return {}
    payload = "".join(f"{resolved_ref}:{path}\n" for path in rel_paths).encode()
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        input=payload,
        capture_output=True,
        check=False,
    )
    texts: dict[str, str] = {}
    if proc.returncode == 0 and proc.stdout:
        texts = parse_cat_file_batch(proc.stdout, rel_paths)
        if len(texts) == len(rel_paths):
            return texts
    for path in rel_paths:
        if path in texts:
            continue
        try:
            texts[path] = read_via_git(repo, resolved_ref, path)
        except subprocess.CalledProcessError:
            continue
    return texts


def load_core_index(
    repo: Path | None,
    ref: str,
    source: dict[str, str],
) -> Any | None:
    """Load default.packages.yaml for the overlay ref (core OOTB list)."""
    from default_packages import (  # noqa: WPS433
        DEFAULT_PACKAGES_REL,
        load_core_index_from_path,
        load_core_index_from_text,
    )

    root = Path(source.get("path", ""))
    on_disk = root / DEFAULT_PACKAGES_REL
    if on_disk.is_file():
        return load_core_index_from_path(on_disk)
    if repo and (repo / ".git").is_dir():
        try:
            resolved = ensure_git_ref(repo, ref)
            text = read_via_git(repo, resolved, DEFAULT_PACKAGES_REL)
            return load_core_index_from_text(text)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return None
    return None


def discover_overlay_repo() -> Path | None:
    env = os.environ.get("RHDH_OVERLAY_REPO")
    if env:
        path = Path(env)
        if path.is_dir():
            return path.resolve()

    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        rhdh_skill = parent / "rhdh"
        if (rhdh_skill / "rhdh" / "config.py").is_file():
            sys.path.insert(0, str(rhdh_skill))
            try:
                from rhdh.config import get_overlay_repo  # type: ignore

                found = get_overlay_repo()
                if found:
                    return Path(found).resolve()
            except Exception:
                pass
        for candidate in (
            parent / OVERLAYS_DIRNAME,
            parent / "repo" / OVERLAYS_DIRNAME,
        ):
            if (candidate / "workspaces").is_dir() or (candidate / "catalog-entities").is_dir():
                return candidate.resolve()
    return None


def clone_overlay(ref: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    clone = subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--filter=blob:none",
            "--sparse",
            "--branch",
            ref,
            OVERLAYS_GIT,
            str(dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if clone.returncode != 0:
        raise FileNotFoundError(
            f"git clone of {OVERLAYS_GIT} ref {ref!r} failed: "
            f"{clone.stderr.strip() or clone.stdout.strip()}"
        )
    sparse = subprocess.run(
        ["git", "-C", str(dest), "sparse-checkout", "set", "--no-cone", *SPARSE_PATTERNS],
        capture_output=True,
        text=True,
        check=False,
    )
    if sparse.returncode != 0:
        raise FileNotFoundError(
            f"sparse-checkout failed: {sparse.stderr.strip() or sparse.stdout.strip()}"
        )
    return dest


def collect_overlay(
    *,
    version: str,
    repo_arg: str | None,
    ref_arg: str | None,
    workdir: bool,
    temp_prefix: str,
    load_workdir: LoadWorkdir,
    load_git: LoadGit,
) -> tuple[list[dict[str, Any]], str, dict[str, str], tempfile.TemporaryDirectory[str] | None]:
    ref = ref_arg or version_to_ref(version)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None

    if repo_arg:
        repo = Path(repo_arg).expanduser().resolve()
        if not repo.is_dir():
            raise FileNotFoundError(f"--repo is not a directory: {repo}")
        if workdir or not (repo / ".git").exists():
            return load_workdir(repo), ref, {"type": "workdir", "path": str(repo)}, temp_dir
        rows, resolved = load_git(repo, ref)
        return rows, resolved, {"type": "local-git", "path": str(repo)}, temp_dir

    discovered = discover_overlay_repo()
    if discovered and (discovered / ".git").exists() and not workdir:
        try:
            rows, resolved = load_git(discovered, ref)
            return rows, resolved, {"type": "local-git", "path": str(discovered)}, temp_dir
        except FileNotFoundError:
            pass

    if discovered and workdir:
        return (
            load_workdir(discovered),
            ref,
            {"type": "workdir", "path": str(discovered)},
            temp_dir,
        )

    temp_dir = tempfile.TemporaryDirectory(prefix=temp_prefix)
    cloned = clone_overlay(ref, Path(temp_dir.name) / OVERLAYS_DIRNAME)
    return load_workdir(cloned), ref, {"type": "clone", "path": str(cloned)}, temp_dir


def collect_overlay_pair(
    *,
    version_from: str,
    version_to: str,
    repo_arg: str | None,
    temp_prefix: str,
    load_git: LoadGit,
    load_workdir: LoadWorkdir | None = None,
) -> tuple[
    list[dict[str, Any]],
    str,
    list[dict[str, Any]],
    str,
    dict[str, str],
    tempfile.TemporaryDirectory[str] | None,
]:
    """Load two overlay refs without switching a user working tree.

    User checkouts are read with `git cat-file --batch`. A throwaway clone
    already has FROM on disk from sparse-checkout; TO is detached-checked-out
    in that clone only.
    """
    ref_from = version_to_ref(version_from)
    ref_to = version_to_ref(version_to)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None

    def load_both(repo: Path) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]], str]:
        from_rows, from_resolved = load_git(repo, ref_from)
        to_rows, to_resolved = load_git(repo, ref_to)
        return from_rows, from_resolved, to_rows, to_resolved

    def load_clone(cloned: Path) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]], str]:
        if load_workdir is None:
            return load_both(cloned)
        from_rows = load_workdir(cloned)
        from_resolved = git_ref_exists(cloned, ref_from) or ref_from
        to_resolved = ensure_git_ref(cloned, ref_to)
        switched = git(cloned, "checkout", "--detach", "--force", to_resolved, check=False)
        if switched.returncode == 0:
            return from_rows, from_resolved, load_workdir(cloned), to_resolved
        to_rows, to_resolved = load_git(cloned, ref_to)
        return from_rows, from_resolved, to_rows, to_resolved

    if repo_arg:
        repo = Path(repo_arg).expanduser().resolve()
        if not repo.is_dir():
            raise FileNotFoundError(f"--repo is not a directory: {repo}")
        if not (repo / ".git").exists():
            raise FileNotFoundError(
                "--diff needs a git checkout of rhdh-plugin-export-overlays "
                "so both versions can be read with git cat-file (not a working tree)."
            )
        from_rows, from_resolved, to_rows, to_resolved = load_both(repo)
        return (
            from_rows,
            from_resolved,
            to_rows,
            to_resolved,
            {"type": "local-git", "path": str(repo)},
            temp_dir,
        )

    discovered = discover_overlay_repo()
    if discovered and (discovered / ".git").exists():
        try:
            from_rows, from_resolved, to_rows, to_resolved = load_both(discovered)
            return (
                from_rows,
                from_resolved,
                to_rows,
                to_resolved,
                {"type": "local-git", "path": str(discovered)},
                temp_dir,
            )
        except FileNotFoundError:
            pass

    temp_dir = tempfile.TemporaryDirectory(prefix=temp_prefix)
    cloned = clone_overlay(ref_from, Path(temp_dir.name) / OVERLAYS_DIRNAME)
    from_rows, from_resolved, to_rows, to_resolved = load_clone(cloned)
    return (
        from_rows,
        from_resolved,
        to_rows,
        to_resolved,
        {"type": "clone", "path": str(cloned)},
        temp_dir,
    )
