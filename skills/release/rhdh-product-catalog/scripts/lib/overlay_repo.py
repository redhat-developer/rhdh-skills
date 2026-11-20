"""Locate, download, or git-show rhdh-plugin-export-overlays without checking out.

Shared by product-catalog scripts. The downloaded tarball is trimmed to
workspaces/*/metadata, catalog-entities/extensions/plugins, and the overlay root
files both scripts read.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

OVERLAYS_GIT = "https://github.com/redhat-developer/rhdh-plugin-export-overlays.git"
OVERLAYS_TARBALL = "https://codeload.github.com/redhat-developer/rhdh-plugin-export-overlays/tar.gz"
OVERLAYS_DIRNAME = "rhdh-plugin-export-overlays"
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.\d+)?$")
RELEASE_BRANCH_RE = re.compile(r"(?:^|/)release-(\d+)\.(\d+)$")
OVERLAY_ROOT_FILES = (
    "default.packages.yaml",
    "rhdh-community-packages.txt",
    "rhdh-supported-packages.txt",
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


def version_number(version: str) -> tuple[int, int] | None:
    match = VERSION_RE.match(version.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def local_release_branches(repo: Path) -> set[tuple[int, int]]:
    proc = git(
        repo,
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/heads/release-*",
        "refs/remotes/origin/release-*",
        check=False,
    )
    branches: set[tuple[int, int]] = set()
    for name in proc.stdout.splitlines():
        match = RELEASE_BRANCH_RE.search(name.strip())
        if match:
            branches.add((int(match.group(1)), int(match.group(2))))
    return branches


def remote_release_branches() -> set[tuple[int, int]]:
    proc = subprocess.run(
        ["git", "ls-remote", "--heads", OVERLAYS_GIT, "refs/heads/release-*"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or str(proc.returncode)
        raise FileNotFoundError(f"cannot list overlay release branches: {detail}")
    branches: set[tuple[int, int]] = set()
    for line in proc.stdout.splitlines():
        ref = line.split("\t")[-1]
        match = RELEASE_BRANCH_RE.search(ref)
        if match:
            branches.add((int(match.group(1)), int(match.group(2))))
    return branches


def resolve_release_ref(
    version: str,
    *,
    ref_arg: str | None = None,
    repo: Path | None = None,
    workdir: bool = False,
    available: set[tuple[int, int]] | None = None,
) -> tuple[str, bool]:
    """Resolve a version to a ref, using main only for the next release.

    A numbered release newer than every existing release branch is pre-GA and
    reads from main. An older missing release branch is an error so stale
    versions are never silently answered from main.
    """
    if ref_arg:
        return ref_arg, False

    requested_ref = version_to_ref(version)
    number = version_number(version)
    if number is None or requested_ref == "main":
        return requested_ref, False

    if available is None:
        if repo is not None and (repo / ".git").exists() and not workdir:
            available = local_release_branches(repo)
            if number in available:
                return requested_ref, False
            # A checkout may be single-branch; ask upstream before deciding
            # whether this is a missing old release or the next release.
            available = remote_release_branches()
        elif repo is None:
            available = remote_release_branches()
        else:
            # A working tree has no refs to inspect; report the requested ref.
            return requested_ref, False

    if number in available:
        return requested_ref, False
    if not available or number > max(available):
        return "main", True
    raise FileNotFoundError(
        f"overlay ref {requested_ref!r} does not exist and {version} is not newer "
        "than the newest release branch"
    )


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

    if source.get("type") in {"workdir", "tarball"}:
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


def source_for_ref(source: dict[str, str], ref: str) -> dict[str, str]:
    """Point a two-ref source at the directory holding `ref`."""
    if source.get("ref_from") == ref and source.get("path_from"):
        return {**source, "path": source["path_from"]}
    return source


def wanted_overlay_path(rel: str) -> bool:
    """True for the overlay paths the product-catalog scripts read."""
    if rel in OVERLAY_ROOT_FILES:
        return True
    parts = rel.split("/")
    if len(parts) != 4:
        return False
    if parts[0] == "workspaces" and parts[2] == "metadata":
        return True
    return parts[:3] == ["catalog-entities", "extensions", "plugins"]


def extract_overlay_tarball(payload: bytes, dest: Path) -> Path:
    """Write the wanted overlay files from a GitHub tarball into `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            _, _, rel = member.name.partition("/")
            if not rel or not wanted_overlay_path(rel):
                continue
            target = dest / rel
            if not target.resolve().is_relative_to(root):
                continue
            source = archive.extractfile(member)
            if source is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
    return dest


def fetch_overlay_tarball(ref: str, dest: Path) -> Path:
    """Download one overlay ref as a tarball and extract the wanted files."""
    url = f"{OVERLAYS_TARBALL}/{urllib.parse.quote(ref, safe='')}"
    request = urllib.request.Request(url, headers={"User-Agent": "rhdh-product-catalog"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise FileNotFoundError(
            f"cannot download overlay ref {ref!r} from {url}: HTTP {exc.code}. "
            "Check the ref, or pass --repo/RHDH_OVERLAY_REPO for a local checkout."
        ) from exc
    except OSError as exc:
        raise FileNotFoundError(
            f"cannot download overlay ref {ref!r} from {url}: {exc}. "
            "Offline? Pass --repo/RHDH_OVERLAY_REPO for a local checkout."
        ) from exc
    return extract_overlay_tarball(payload, dest)


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
    temp_dir: tempfile.TemporaryDirectory[str] | None = None

    if repo_arg:
        repo = Path(repo_arg).expanduser().resolve()
        if not repo.is_dir():
            raise FileNotFoundError(f"--repo is not a directory: {repo}")
        ref, pre_release = resolve_release_ref(version, ref_arg=ref_arg, repo=repo, workdir=workdir)
        source = {"type": "workdir" if workdir or not (repo / ".git").exists() else "local-git"}
        source["path"] = str(repo)
        if pre_release:
            source["pre_release"] = "true"
        if workdir or not (repo / ".git").exists():
            return load_workdir(repo), ref, source, temp_dir
        rows, resolved = load_git(repo, ref)
        return rows, resolved, source, temp_dir

    discovered = discover_overlay_repo()
    if discovered and workdir:
        ref, pre_release = resolve_release_ref(
            version, ref_arg=ref_arg, repo=discovered, workdir=workdir
        )
        source = {"type": "workdir", "path": str(discovered)}
        if pre_release:
            source["pre_release"] = "true"
        return load_workdir(discovered), ref, source, temp_dir

    if discovered and (discovered / ".git").exists():
        try:
            ref, pre_release = resolve_release_ref(
                version, ref_arg=ref_arg, repo=discovered, workdir=workdir
            )
            rows, resolved = load_git(discovered, ref)
            source = {"type": "local-git", "path": str(discovered)}
            if pre_release:
                source["pre_release"] = "true"
            return rows, resolved, source, temp_dir
        except FileNotFoundError:
            pass

    ref, pre_release = resolve_release_ref(version, ref_arg=ref_arg)
    temp_dir = tempfile.TemporaryDirectory(prefix=temp_prefix)
    root = fetch_overlay_tarball(ref, Path(temp_dir.name) / OVERLAYS_DIRNAME)
    source = {"type": "tarball", "path": str(root)}
    if pre_release:
        source["pre_release"] = "true"
    return load_workdir(root), ref, source, temp_dir


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

    User checkouts are read with `git cat-file --batch`. Without one, each ref
    is downloaded as its own tarball so neither version is checked out.
    """
    repo: Path | None = None
    if repo_arg:
        repo = Path(repo_arg).expanduser().resolve()
        if not repo.is_dir():
            raise FileNotFoundError(f"--repo is not a directory: {repo}")
        if not (repo / ".git").exists():
            raise FileNotFoundError(
                "--diff needs a git checkout of rhdh-plugin-export-overlays "
                "so both versions can be read with git cat-file (not a working tree)."
            )
    else:
        discovered = discover_overlay_repo()
        if discovered and (discovered / ".git").exists():
            repo = discovered

    available = remote_release_branches() if repo is None else None
    ref_from, pre_release_from = resolve_release_ref(version_from, repo=repo, available=available)
    ref_to, pre_release_to = resolve_release_ref(version_to, repo=repo, available=available)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None

    if repo is not None:
        from_rows, from_resolved = load_git(repo, ref_from)
        to_rows, to_resolved = load_git(repo, ref_to)
        source = {"type": "local-git", "path": str(repo)}
        if pre_release_from:
            source["pre_release_from"] = "true"
        if pre_release_to:
            source["pre_release_to"] = "true"
        return from_rows, from_resolved, to_rows, to_resolved, source, temp_dir

    if load_workdir is None:
        raise FileNotFoundError("cannot read two overlay refs: no working-tree loader was supplied")
    temp_dir = tempfile.TemporaryDirectory(prefix=temp_prefix)
    base = Path(temp_dir.name)
    from_root = fetch_overlay_tarball(ref_from, base / "from")
    to_root = fetch_overlay_tarball(ref_to, base / "to")
    source = {
        "type": "tarball",
        "path": str(to_root),
        "path_from": str(from_root),
        "ref_from": ref_from,
    }
    if pre_release_from:
        source["pre_release_from"] = "true"
    if pre_release_to:
        source["pre_release_to"] = "true"
    return (
        load_workdir(from_root),
        ref_from,
        load_workdir(to_root),
        ref_to,
        source,
        temp_dir,
    )
