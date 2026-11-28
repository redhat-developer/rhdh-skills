#!/usr/bin/env python3
"""Resolve a release tag or EOL branch, then run rhdh-operator hack/eol-release.sh.

Never commits, pushes, or opens a pull request. JSON goes to stdout; the
operator script's log goes to stderr.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RELEASE_TAG = re.compile(r"^[0-9]+\.[0-9]+\.0$")
RELEASE_BRANCH = re.compile(r"^release-[0-9]+\.[0-9]+$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+$")
UPDATE_LINE = re.compile(r"^update\s+(\S+)\s*$")
KEY_LINE = re.compile(r"^(EOL_BRANCH|CHANGED)=(.*)$")


def die(message: str, code: int = 2) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def version_key(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in tag.split("."))


def git_tags(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "tag", "--list"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        die(result.stderr.strip() or f"git tag --list failed in {root}")
    tags = [line for line in result.stdout.splitlines() if RELEASE_TAG.fullmatch(line)]
    tags.sort(key=version_key)
    return tags


def normalize_branch(value: str) -> str:
    if RELEASE_BRANCH.fullmatch(value):
        return value
    if VERSION.fullmatch(value):
        return f"release-{value}"
    die(f"not a release branch (expected release-x.y): {value}")
    raise AssertionError(value)


def tag_for_branch(root: Path, branch: str) -> str:
    branch = normalize_branch(branch)
    eol_tag = f"{branch.removeprefix('release-')}.0"
    tags = git_tags(root)
    try:
        index = tags.index(eol_tag)
    except ValueError:
        die(f"{eol_tag} is not a release tag in {root}")
    trigger_index = index + 2
    if trigger_index >= len(tags):
        die(f"not enough release history to EOL {branch}; need a tag two releases after {eol_tag}")
    return tags[trigger_index]


def parse_operator_log(log: str) -> tuple[str, bool, list[str]]:
    eol_branch = ""
    changed = False
    files: list[str] = []
    for line in log.splitlines():
        update = UPDATE_LINE.match(line)
        if update:
            files.append(update.group(1))
            continue
        key = KEY_LINE.match(line)
        if not key:
            continue
        name, value = key.group(1), key.group(2)
        if name == "EOL_BRANCH":
            eol_branch = value
        elif name == "CHANGED":
            changed = value == "true"
    return eol_branch, changed, files


def run_operator(root: Path, tag: str, write: bool) -> str:
    script = root / "hack" / "eol-release.sh"
    if not script.is_file():
        die(f"missing {script}")
    command = [str(script), "--tag", tag, "--root", str(root)]
    if write:
        command.append("--write")
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.stderr:
        sys.stderr.write(result.stderr)
        if not result.stderr.endswith("\n"):
            sys.stderr.write("\n")
    if result.stdout:
        sys.stderr.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stderr.write("\n")
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.stdout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve a release tag or EOL branch, then run rhdh-operator "
            "hack/eol-release.sh. Prints one JSON object. Does not commit or push."
        )
    )
    parser.add_argument("--root", required=True, help="rhdh-operator repository root")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tag", help="release tag that just shipped, e.g. 2.1.0")
    source.add_argument("--branch", help="EOL branch, e.g. release-1.9 or 1.9")
    parser.add_argument(
        "--write",
        action="store_true",
        help="apply the operator script edits (default: dry-run)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    if not (root / ".github").is_dir():
        die(f"not a repository root: {root}")

    if args.tag:
        if not RELEASE_TAG.fullmatch(args.tag):
            die(f"not a release tag (expected x.y.0): {args.tag}")
        tag = args.tag
    else:
        tag = tag_for_branch(root, args.branch)

    log = run_operator(root, tag, write=args.write)
    eol_branch, changed, files = parse_operator_log(log)
    payload = {
        "tag": tag,
        "eol_branch": eol_branch,
        "changed": changed,
        "write": bool(args.write),
        "root": str(root),
        "files": files,
    }
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
