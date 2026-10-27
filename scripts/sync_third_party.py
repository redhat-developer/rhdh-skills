#!/usr/bin/env python3
"""Sync vendored third-party skills with their pinned upstream sources.

Each ``skills/third-party/<name>/UPSTREAM.toml`` records where the skill came
from (``source``, ``path``, ``ref``) and how it tracks upstream (``mode``):

- ``tracked`` — the vendored files must match the pinned upstream ref exactly.
  ``--write`` overwrites them from upstream; ``--check`` fails on drift.
- ``adapted`` — we forked the skill. Sync never touches it; drift against the
  pinned ref is reported as local modifications so a human can re-port upstream
  changes deliberately.

Refresh flow: resolve the new upstream commit (``git ls-remote <url> main``),
edit ``ref`` in ``UPSTREAM.toml``, run ``--write``, review the diff.

Files this repo adds on top of upstream (``UPSTREAM.toml`` itself, harness
metadata upstream does not ship) are preserved and never removed.

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
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
THIRD_PARTY_ROOT = REPO_ROOT / "skills" / "third-party"
UPSTREAM_FILE = "UPSTREAM.toml"
MODES = ("tracked", "adapted")
# UPSTREAM.toml is our own fixed format (source, path, ref, mode — all
# strings), so a strict line parser is enough; tomllib needs Python 3.11.
_LINE = re.compile(r'^([a-z]+)\s*=\s*"([^"]*)"$')
FIELDS = ("source", "path", "ref", "mode")


class SyncError(Exception):
    """A UPSTREAM.toml or upstream fetch problem."""


def parse_upstream_toml(text: str, origin: Path) -> dict[str, str]:
    """Parse the fixed four-field UPSTREAM.toml format."""
    fields: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if match is None:
            raise SyncError(f'{origin}:{number}: not a `key = "value"` line: {raw!r}')
        key, value = match.groups()
        if key not in FIELDS:
            raise SyncError(f"{origin}:{number}: unknown field {key!r}")
        if key in fields:
            raise SyncError(f"{origin}:{number}: duplicate field {key!r}")
        fields[key] = value
    missing = [field for field in FIELDS if not fields.get(field)]
    if missing:
        raise SyncError(f"{origin}: missing or empty fields: {', '.join(missing)}")
    if fields["mode"] not in MODES:
        raise SyncError(f"{origin}: mode must be one of {MODES}, got {fields['mode']!r}")
    owner, _, repo = fields["source"].partition("/")
    if not (owner and repo) or "/" in repo or fields["path"].startswith("/"):
        raise SyncError(f"{origin}: source must be owner/repo and path must be relative")
    return fields


def discover_skills(root: Path) -> dict[str, tuple[Path, dict[str, str]]]:
    """Return {skill name: (vendored directory, UPSTREAM.toml fields)}."""
    skills: dict[str, tuple[Path, dict[str, str]]] = {}
    if not root.is_dir():
        return skills
    for upstream in sorted(root.glob(f"*/{UPSTREAM_FILE}")):
        skill_dir = upstream.parent
        fields = parse_upstream_toml(upstream.read_text(encoding="utf-8"), upstream)
        skills[skill_dir.name] = (skill_dir, fields)
    orphan = sorted(
        path.parent.name
        for path in root.glob("*/SKILL.md")
        if not (path.parent / UPSTREAM_FILE).is_file()
    )
    if orphan:
        raise SyncError(f"skills under {root} without {UPSTREAM_FILE}: {', '.join(orphan)}")
    return skills


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


def _vendored_files(skill_dir: Path) -> Iterator[Path]:
    for path in sorted(skill_dir.rglob("*")):
        if path.is_file() and UPSTREAM_FILE != path.name and "__pycache__" not in path.parts:
            yield path


def compare_skill(
    skill_dir: Path, fields: dict[str, str], upstream_files: dict[Path, bytes]
) -> dict[str, list[str]]:
    """Report how a vendored skill differs from its pinned upstream files."""
    upstream_prefix = Path(fields["path"])
    expected = {
        path.relative_to(upstream_prefix): content
        for path, content in upstream_files.items()
        if path == upstream_prefix or upstream_prefix in path.parents
    }
    if not expected:
        raise SyncError(f"{skill_dir.name}: upstream has no files at {fields['path']!r}")

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
    skill_dir: Path, fields: dict[str, str], upstream_files: dict[Path, bytes]
) -> list[str]:
    """Overwrite tracked vendored files from upstream; return written paths."""
    upstream_prefix = Path(fields["path"])
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


def sync(root: Path, write: bool = False) -> tuple[list[dict[str, object]], bool]:
    """Sync every vendored skill; return (per-skill reports, check-clean flag)."""
    skills = discover_skills(root)
    if not skills:
        raise SyncError(f"no vendored skills under {root}")

    archives: dict[tuple[str, str], dict[Path, bytes]] = {}
    clean = True
    reports: list[dict[str, object]] = []
    for name, (skill_dir, fields) in sorted(skills.items()):
        key = (fields["source"], fields["ref"])
        if key not in archives:
            archives[key] = fetch_upstream_files(*key)
        upstream_files = archives[key]
        report = compare_skill(skill_dir, fields, upstream_files)
        action = "reported"
        if fields["mode"] == "tracked":
            drifted = bool(report["changed"] or report["missing"])
            if drifted and write:
                apply_skill(skill_dir, fields, upstream_files)
                action = "refreshed"
            elif drifted:
                clean = False
                action = "drift"
        else:
            action = "adapted-local-modifications" if report["changed"] else "adapted"
        reports.append({"skill": name, "mode": fields["mode"], "action": action, **report})
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
