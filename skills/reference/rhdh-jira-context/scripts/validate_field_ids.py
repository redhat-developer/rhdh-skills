#!/usr/bin/env python3
"""Validate Jira custom-field IDs against references/fields.md and live Jira.

The custom-field IDs are duplicated into every skill that reads Jira, because
bundled scripts are self-contained. A stale copy fails *silently* — the
extractor reads a `customfield_*` key that is not there, yields "" or None, and
the caller reports missing data rather than an error. Nothing surfaces it. This
script is what makes that failure loud.

Two checks, independent:

  Copies   Every FIELDS dict in the repo agrees with references/fields.md.
           Pure static comparison, no network, no credentials. This is the check
           that catches the real failure mode, so it runs by default and is the
           one worth wiring into CI.

  Live     The IDs in fields.md are still the IDs Jira uses. Needs `acli`, which
           holds its own credentials; nothing secret enters arguments or output.

Usage:
  python scripts/validate_field_ids.py                 # copies only, offline
  python scripts/validate_field_ids.py --live          # copies + live Jira
  python scripts/validate_field_ids.py --live --sample RHIDP-1 RHDHPLAN-1
  python scripts/validate_field_ids.py --json

Exit codes:
  0  Everything agrees
  1  Drift detected
  2  Argument or repository-layout error
  3  acli not found (only with --live)
  4  Jira request failed (only with --live)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# `| Team | `customfield_10001` | ... |` in the Custom Fields table.
FIELDS_MD_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*`(customfield_\d+)`\s*\|")
# `"team": lambda i: _name(i, "customfield_10001"),` in a FIELDS dict.
FIELDS_PY_ENTRY = re.compile(r'"([a-z_]+)"\s*:.*?"(customfield_\d+)"', re.DOTALL)
# A bare id anywhere else in a script, e.g. inside _sprint_name.
ANY_FIELD_ID = re.compile(r'"(customfield_\d+)"')

# Every script that carries a copy of the IDs. Keep this list in step with the
# warning comment each of those files carries.
COPY_PATHS = (
    "skills/reference/rhdh-jira-api/scripts/parse_issues.py",
    "skills/release/rhdh-release-announce/scripts/_jira.py",
    "skills/release/rhdh-release-schedule/scripts/_jira.py",
    "skills/release/rhdh-release-status/scripts/_jira.py",
    "skills/release/rhdh-release-teams/scripts/_jira.py",
)

DEFAULT_SAMPLE = ("RHIDP-1", "RHDHPLAN-1", "RHDHBUGS-1", "RHDHSUPP-1")


def repo_root(script: Path) -> Path:
    """Walk up to the checkout root so the copy list resolves from anywhere."""
    for candidate in [script, *script.parents]:
        if (candidate / "skills").is_dir() and (candidate / "docs").is_dir():
            return candidate
    return script.parents[4]


def documented_ids(fields_path: Path) -> dict[str, str]:
    """Map field id -> documented name, from the Custom Fields table."""
    documented: dict[str, str] = {}
    for line in fields_path.read_text(encoding="utf-8").splitlines():
        match = FIELDS_MD_ROW.match(line)
        if match:
            name, field_id = match.groups()
            documented[field_id] = name
    return documented


def ids_in_copy(path: Path) -> dict[str, str]:
    """Map field id -> the accessor key that reads it, for one copy."""
    text = path.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for key, field_id in FIELDS_PY_ENTRY.findall(text):
        found.setdefault(field_id, key)
    # Ids used outside a FIELDS entry still have to be real.
    for field_id in ANY_FIELD_ID.findall(text):
        found.setdefault(field_id, "<used outside FIELDS>")
    return found


def fetch_live_ids(acli: str, issue_keys: list[str]) -> tuple[set[str], list[str]]:
    """Return the custom-field ids Jira returns, and the keys that failed.

    Jira only reports fields it holds for the sampled issues, so absence here is
    weaker evidence than presence. Sampling one issue per project widens
    coverage; the caller still reports a miss as suspected rather than proven.
    """
    seen: set[str] = set()
    unreadable: list[str] = []
    for key in issue_keys:
        try:
            result = subprocess.run(
                [acli, "jira", "workitem", "view", key, "--fields", "*all", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if result.returncode != 0:
                unreadable.append(key)
                continue
            payload = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            unreadable.append(key)
            continue

        fields = payload.get("fields", payload)
        if isinstance(fields, dict):
            seen.update(name for name in fields if name.startswith("customfield_"))
    return seen, unreadable


def check_copies(root: Path, documented: dict[str, str]) -> list[dict[str, str]]:
    """Report every id in a copy that fields.md does not document."""
    findings: list[dict[str, str]] = []
    for relative in COPY_PATHS:
        path = root / relative
        if not path.exists():
            findings.append(
                {
                    "code": "COPY_MISSING",
                    "path": relative,
                    "detail": "listed as carrying the field IDs but not found; update COPY_PATHS",
                }
            )
            continue
        for field_id, accessor in sorted(ids_in_copy(path).items()):
            if field_id not in documented:
                findings.append(
                    {
                        "code": "COPY_UNDOCUMENTED_ID",
                        "path": relative,
                        "detail": (
                            f"{field_id} (read as '{accessor}') is not in fields.md; "
                            f"the copy has drifted or fields.md is out of date"
                        ),
                    }
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--live",
        action="store_true",
        help="Also check fields.md against live Jira through acli",
    )
    parser.add_argument(
        "--sample",
        nargs="+",
        metavar="KEY",
        default=list(DEFAULT_SAMPLE),
        help="Issue keys to sample for live field metadata",
    )
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON")
    args = parser.parse_args()

    script = Path(__file__).resolve()
    root = repo_root(script)
    fields_path = script.parent.parent / "references" / "fields.md"
    if not fields_path.exists():
        print(f"fields.md not found at {fields_path}", file=sys.stderr)
        return 2

    documented = documented_ids(fields_path)
    if not documented:
        print(f"No custom-field rows parsed from {fields_path}", file=sys.stderr)
        return 2

    findings = check_copies(root, documented)
    unreadable: list[str] = []
    unobserved: list[str] = []

    if args.live:
        acli = shutil.which("acli")
        if not acli:
            print("acli not found. Run /setup-rhdh-skills jira.", file=sys.stderr)
            return 3
        live, unreadable = fetch_live_ids(acli, args.sample)
        if not live and len(unreadable) == len(args.sample):
            print(
                f"Could not read any sampled issue ({', '.join(unreadable)}).",
                file=sys.stderr,
            )
            return 4
        unobserved = sorted(set(documented) - live)
        for field_id in unobserved:
            findings.append(
                {
                    "code": "ID_NOT_OBSERVED",
                    "path": "references/fields.md",
                    "detail": (
                        f"{field_id} ({documented[field_id]}) appeared on none of the "
                        f"sampled issues; it may have been removed, or simply be unset "
                        f"on all of them — confirm before editing"
                    ),
                }
            )

    if args.json_output:
        print(
            json.dumps(
                {
                    "documentedCount": len(documented),
                    "copiesChecked": len(COPY_PATHS),
                    "liveChecked": args.live,
                    "unreadableSamples": unreadable,
                    "findings": findings,
                    "inSync": not findings,
                },
                indent=2,
            )
        )
        return 0 if not findings else 1

    print(f"Documented custom fields: {len(documented)}")
    print(f"Copies checked:           {len(COPY_PATHS)}")
    if args.live:
        print(f"Sampled issues:           {', '.join(args.sample)}")
        if unreadable:
            print(f"  unreadable:             {', '.join(unreadable)}")
    print()

    if not findings:
        print("All field IDs agree with references/fields.md.")
        return 0

    for finding in findings:
        print(f"{finding['code']}  {finding['path']}")
        print(f"    {finding['detail']}")
    print()
    print(f"Drift detected: {len(findings)} finding(s).")
    if unobserved:
        print("An ID reported as not observed is a lead, not a verdict: Jira omits")
        print("fields it holds no value for. Widen --sample before editing a copy.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
