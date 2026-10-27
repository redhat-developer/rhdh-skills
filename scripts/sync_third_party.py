#!/usr/bin/env python3
"""Sync vendored third-party skills with their pinned upstream sources.

``skills/third-party/registry.json`` is the single metadata config for every
vendored skill. ``sources`` maps each ``owner/repo`` to the subdirectory it is
vendored under (``directory``), one pinned ``ref``, its ``license``, and the
``skills`` vendored from it — each with ``name`` (the vendored directory),
``path`` inside that repository, and ``mode``:

- ``tracked`` — the vendored files must match the pinned upstream ref exactly.
  ``--write`` overwrites them from upstream; ``--check`` fails on drift.
- ``adapted`` — we forked the skill. Sync never touches it; drift against the
  pinned ref is reported as local modifications so a human can re-port upstream
  changes deliberately.

Refresh flow: resolve the new upstream commit (``git ls-remote <url> main``),
edit the source's ``ref`` in ``registry.json``, run ``--write``, review the
diff. Bumping a source refreshes every skill vendored from it.

Files this repo adds on top of upstream (harness metadata upstream does not
ship) are preserved and never removed. The registry must list exactly the skill directories that exist under
``skills/third-party/``, one ``<directory>/<name>`` pair per skill. Skill names
are unique across sources: two vendors shipping the same name is a collision
the catalog could not express. An empty registry (no sources) is valid:
nothing to sync, nothing on disk.

    python scripts/sync_third_party.py           # report drift, exit 0
    python scripts/sync_third_party.py --check   # exit 1 on tracked drift
    python scripts/sync_third_party.py --write   # refresh tracked skills

Stdlib only (ADR-0002). Requires network access to codeload.github.com.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
THIRD_PARTY_ROOT = REPO_ROOT / "skills" / "third-party"
REGISTRY_FILE = "registry.json"
MODES = ("tracked", "adapted")
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SKILL_FIELDS = ("name", "path", "mode")
SOURCE_FIELDS = ("directory", "ref", "license", "skills")


class SyncError(Exception):
    """A registry or upstream fetch problem."""


def load_registry(root: Path) -> list[dict[str, str]]:
    """Load the third-party skill registry and flatten sources into skill entries.

    Returns one flat entry per skill (name, source, path, directory, ref,
    license, mode). The ref lives on the source, so every skill from one
    upstream repository is pinned to the same commit by construction, and the
    vendored path is ``<directory>/<name>`` under the third-party root.
    """
    registry_file = root / REGISTRY_FILE
    if not registry_file.is_file():
        raise SyncError(f"no {REGISTRY_FILE} under {root}")
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SyncError(f"{registry_file}: {error}") from error

    if registry.get("schemaVersion") != 1:
        raise SyncError(f"{registry_file}: schemaVersion must be 1")
    sources = registry.get("sources")
    if not isinstance(sources, dict):
        raise SyncError(f"{registry_file}: sources must be an object")
    for source, meta in sources.items():
        origin = f"{registry_file} sources[{source!r}]"
        owner, _, repo = source.partition("/")
        if not (owner and repo) or "/" in repo:
            raise SyncError(f"{origin}: source key must be owner/repo")
        if not isinstance(meta, dict):
            raise SyncError(f"{origin}: must be an object")
        missing = [field for field in SOURCE_FIELDS if field != "skills" and not meta.get(field)]
        if missing:
            raise SyncError(f"{origin}: missing or empty fields: {', '.join(missing)}")
        if not SKILL_NAME.fullmatch(meta["directory"]):
            raise SyncError(
                f"{origin}: directory must be a single kebab-case segment, "
                f"got {meta['directory']!r}"
            )
        skills = meta.get("skills")
        if not isinstance(skills, list) or not skills:
            raise SyncError(f"{origin}: skills must be a non-empty array")

    loaded: list[dict[str, str]] = []
    seen: set[str] = set()
    for source, meta in sources.items():
        for index, entry in enumerate(meta["skills"]):
            origin = f"{registry_file} sources[{source!r}].skills[{index}]"
            if not isinstance(entry, dict):
                raise SyncError(f"{origin}: must be an object")
            missing = [field for field in SKILL_FIELDS if not entry.get(field)]
            if missing:
                raise SyncError(f"{origin}: missing or empty fields: {', '.join(missing)}")
            unknown = sorted(set(entry) - set(SKILL_FIELDS))
            if unknown:
                raise SyncError(f"{origin}: unknown fields: {', '.join(unknown)}")
            name = entry["name"]
            if not SKILL_NAME.fullmatch(name):
                raise SyncError(f"{origin}: name must be kebab-case, got {name!r}")
            if name in seen:
                raise SyncError(f"{origin}: duplicate skill {name!r}")
            seen.add(name)
            if entry["path"].startswith("/"):
                raise SyncError(f"{origin}: path must be relative")
            if entry["mode"] not in MODES:
                raise SyncError(f"{origin}: mode must be one of {MODES}, got {entry['mode']!r}")
            loaded.append(
                {
                    **{field: entry[field] for field in SKILL_FIELDS},
                    "source": source,
                    "directory": meta["directory"],
                    "ref": meta["ref"],
                    "license": meta["license"],
                }
            )
    return loaded


def fetch_upstream_files(source: str, ref: str) -> dict[Path, bytes]:
    """Download the source tarball at ref and return {relative path: bytes}."""
    url = f"https://codeload.github.com/{source}/tar.gz/{ref}"
    with tempfile.TemporaryFile() as buffer:
        with urllib.request.urlopen(url) as response:  # noqa: S310 - fixed https host
            buffer.write(response.read())
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r:gz") as archive:
            return {
                Path(member.name).relative_to(Path(member.name).parts[0]): archive.extractfile(
                    member
                ).read()
                for member in archive.getmembers()
                if member.isfile() and "/" in member.name
            }


def _vendored_files(skill_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]


def compare_skill(
    skill_dir: Path, entry: dict[str, str], upstream_files: dict[Path, bytes]
) -> dict[str, list[str]]:
    """Report how a vendored skill differs from its pinned upstream files."""
    upstream_prefix = Path(entry["path"])
    expected = {
        path.relative_to(upstream_prefix): content
        for path, content in upstream_files.items()
        if path == upstream_prefix or upstream_prefix in path.parents
    }
    if not expected:
        raise SyncError(f"{entry['name']}: upstream has no files at {entry['path']!r}")

    present = {path.relative_to(skill_dir): path for path in _vendored_files(skill_dir)}
    report: dict[str, list[str]] = {
        "changed": [],
        "missing": [],
        "local_only": [],
    }
    for relative, content in sorted(expected.items()):
        vendored = present.get(relative)
        if vendored is None:
            report["missing"].append(relative.as_posix())
        elif vendored.read_bytes() != content:
            report["changed"].append(relative.as_posix())
    for relative in sorted(set(present) - set(expected)):
        report["local_only"].append(relative.as_posix())
    return report


def apply_skill(
    skill_dir: Path, entry: dict[str, str], upstream_files: dict[Path, bytes]
) -> list[str]:
    """Overwrite tracked vendored files from upstream; return written paths."""
    upstream_prefix = Path(entry["path"])
    written: list[str] = []
    for path, content in sorted(upstream_files.items()):
        if path != upstream_prefix and upstream_prefix not in path.parents:
            continue
        relative = path.relative_to(upstream_prefix)
        target = skill_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        written.append(relative.as_posix())
    return written


def skill_dir_for(root: Path, entry: dict[str, str]) -> Path:
    """The vendored directory for a registry entry: <root>/<directory>/<name>."""
    return root / entry["directory"] / entry["name"]


def sync(root: Path, write: bool = False) -> tuple[list[dict[str, Any]], bool]:
    """Sync every vendored skill; return (per-skill reports, check-clean flag)."""
    entries = load_registry(root)

    on_disk = {path.parent for path in root.glob("*/*/SKILL.md")}
    registered = {skill_dir_for(root, entry) for entry in entries}
    unregistered = sorted(path.name for path in on_disk - registered)
    missing = sorted(path.name for path in registered - on_disk)
    if unregistered:
        raise SyncError(
            f"skills under {root} missing from {REGISTRY_FILE}: {', '.join(unregistered)}"
        )
    if missing:
        raise SyncError(f"{REGISTRY_FILE} lists skills with no directory: {', '.join(missing)}")

    archives: dict[tuple[str, str], dict[Path, bytes]] = {}
    clean = True
    reports: list[dict[str, Any]] = []
    for entry in entries:
        skill_dir = skill_dir_for(root, entry)
        key = (entry["source"], entry["ref"])
        if key not in archives:
            archives[key] = fetch_upstream_files(*key)
        upstream_files = archives[key]
        report = compare_skill(skill_dir, entry, upstream_files)
        action = "reported"
        if entry["mode"] == "tracked":
            drifted = bool(report["changed"] or report["missing"])
            if drifted and write:
                apply_skill(skill_dir, entry, upstream_files)
                action = "refreshed"
            elif drifted:
                clean = False
                action = "drift"
        else:
            action = "adapted-local-modifications" if report["changed"] else "adapted"
        reports.append({"skill": entry["name"], "mode": entry["mode"], "action": action, **report})
    return reports, clean


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(THIRD_PARTY_ROOT), help=argparse.SUPPRESS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="refresh tracked skills from upstream")
    mode.add_argument("--check", action="store_true", help="exit 1 on tracked drift")
    args = parser.parse_args(argv)

    try:
        reports, clean = sync(Path(args.root), write=args.write)
    except (SyncError, OSError, tarfile.TarError) as error:
        json.dump({"ok": False, "error": str(error)}, sys.stdout, indent=2)
        print()
        return 2

    json.dump({"ok": True, "clean": clean, "skills": reports}, sys.stdout, indent=2)
    print()
    if args.check and not clean:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
