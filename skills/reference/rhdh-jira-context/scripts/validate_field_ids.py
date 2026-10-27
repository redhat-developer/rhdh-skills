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

  Live     The IDs in fields.md are still the IDs Jira uses. Needs issue JSON,
           holds its own credentials; nothing secret enters arguments or output.

Usage:
  python scripts/validate_field_ids.py                    # copies only
  python scripts/validate_field_ids.py --from-json a.json # + live Jira
  # a.json: output of `acli jira workitem view KEY --fields "*all" --json`,
  # fetched by the agent; one file per sampled issue
  python scripts/validate_field_ids.py --json

Exit codes:
  0  Everything agrees
  1  Drift detected
  2  Argument or repository-layout error
  3  No readable issue JSON supplied (only with --from-json)
"""

from __future__ import annotations

import argparse
import json
import re
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
    "skills/reference/rhdh-jira-context/scripts/parse_issues.py",
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


def load_live_ids(paths: list[str]) -> tuple[set[str], list[str]]:
    """Return the custom-field ids seen in fetched issue JSON, and unreadable paths.

    The agent fetches the issues with whichever Jira tool it has (for example
    `acli jira workitem view KEY --fields "*all" --json`) and saves each
    payload to a file; this script never runs a tool itself. Jira only reports
    fields it holds for the sampled issues, so absence here is weaker evidence
    than presence. Sampling one issue per project widens coverage; the caller
    still reports a miss as suspected rather than proven.
    """
    seen: set[str] = set()
    unreadable: list[str] = []
    for path in paths:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            unreadable.append(path)
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
        "--from-json",
        nargs="+",
        metavar="ISSUE_JSON",
        default=[],
        help="paths to fetched issue payloads (workitem view --fields '*all' --json)",
    )
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON")
    args = parser.parse_args()

    root = repo_root(Path(__file__).resolve())
    fields_path = root / "skills" / "reference" / "rhdh-jira-context" / "references" / "fields.md"
    documented = documented_ids(fields_path)

    findings = check_copies(root, documented)
    unreadable: list[str] = []
    unobserved: list[str] = []

    if args.from_json:
        live, unreadable = load_live_ids(args.from_json)
        if not live and len(unreadable) == len(args.from_json):
            print(
                f"Could not read any supplied issue JSON ({', '.join(unreadable)}).",
                file=sys.stderr,
            )
            return 3
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
                    "liveChecked": bool(args.from_json),
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
    if args.from_json:
        print(f"Sampled issue files:      {len(args.from_json)}")
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
        print("fields it holds no value for. Widen the sample before editing a copy.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
