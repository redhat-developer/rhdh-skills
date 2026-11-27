"""Resolve RHDH z-stream release candidates from product repository tags.

Read-only: ``git ls-remote`` lists remote refs and changes nothing. A tag is a
candidate, never proof that the product shipped; the caller still reads the
release notes before setting ``--current-release``.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any, Dict, List

DEFAULT_RELEASE_REPOSITORIES = ("redhat-developer/rhdh",)
RELEASE_TAG_RE = re.compile(r"refs/tags/(\d+)\.(\d+)\.(\d+)")
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
LIMITS = (
    "A tag is a candidate, not proof of shipment. Read both release-notes pages "
    "and confirm the z-stream section before setting --current-release."
)


def release_key(version: str) -> tuple:
    """Sort key for an x.y.z version; callers pass versions this module produced."""
    return tuple(int(part) for part in version.split("."))


def _tag_refs(output: str) -> List[str]:
    refs = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].strip().startswith("refs/tags/"):
            refs.append(parts[1].strip())
    return refs


def parse_release_tags(output: str) -> List[str]:
    """Keep only exact ``refs/tags/x.y.z`` refs.

    ``redhat-developer-hub-2.1.0`` is a chart version, ``2.1`` is a stream, and
    ``v0.2.0`` is not the product scheme; none of them identifies a z-stream.
    Peeled ``^{}`` refs are the annotated-tag companions of a ref already seen.
    """
    versions = set()
    for ref in _tag_refs(output):
        match = RELEASE_TAG_RE.fullmatch(ref)
        if match:
            versions.add(".".join(match.groups()))
    return sorted(versions, key=release_key)


def read_release_tags(repository: str, timeout: int = 60) -> str:
    """List remote tags without a checkout; no credentials or writes involved."""
    if not REPOSITORY_RE.fullmatch(repository):
        raise ValueError(f"expected a GitHub owner/repo, got {repository!r}")
    url = f"https://github.com/{repository}.git"
    try:
        completed = subprocess.run(
            ["git", "ls-remote", "--tags", url],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        raise ValueError("git is not on PATH") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"git ls-remote timed out after {timeout}s for {repository}") from error
    if completed.returncode:
        message = (completed.stderr or completed.stdout or "").strip()
        raise ValueError(f"git ls-remote failed for {repository}: {message}")
    return completed.stdout


def describe_repository(repository: str, output: str) -> Dict[str, Any]:
    tags = parse_release_tags(output)
    matched = {f"refs/tags/{version}" for version in tags}
    refs = _tag_refs(output)
    return {
        "repository": repository,
        "latest": tags[-1] if tags else None,
        "tags": tags,
        "ignoredTagRefs": len({ref for ref in refs if ref not in matched}),
    }


def release_notes_urls(version: str) -> Dict[str, List[str]]:
    """Both documented page layouts, because 2.x moved off the ``/html/`` paths."""
    major, minor, _ = version.split(".")
    stream = f"{major}.{minor}"
    base = f"https://docs.redhat.com/en/documentation/red_hat_developer_hub/{stream}"
    legacy = f"{base}/html/red_hat_developer_hub_release_notes"
    return {
        "fixedIssues": [
            f"{legacy}/fixed-issues",
            f"{base}/whats_new-fixed_issues",
        ],
        "fixedSecurityIssues": [
            f"{legacy}/fixed-security-issues",
            f"{base}/whats_new-fixed_security_issues",
        ],
    }


def resolve_release(repositories: List[str], timeout: int = 60) -> Dict[str, Any]:
    rows = [
        describe_repository(repository, read_release_tags(repository, timeout))
        for repository in repositories
    ]
    latests = {row["latest"] for row in rows if row["latest"]}
    agreement = len(latests) <= 1
    latest = next(iter(latests)) if agreement and latests else None
    return {
        "repositories": rows,
        "latest": latest,
        "agreement": agreement,
        "releaseNotes": release_notes_urls(latest) if latest else {},
        "limits": LIMITS,
    }
