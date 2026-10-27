#!/usr/bin/env python3
"""Validate components in fields.md against live Jira project data.

Compares the Component Catalog table in references/fields.md against the
components actually configured in RHIDP and RHDHPLAN Jira projects. Reports
components that exist in Jira but are missing from fields.md, and components
listed in fields.md that no longer exist in Jira.

Usage:
  python scripts/validate_components.py
  python scripts/validate_components.py --json

Requires:
  - acli authenticated through its native credential store
  - Network access to the configured Jira site

Exit codes:
  0  All components match
  1  Drift detected (missing or extra components)
  2  Argument error
  3  acli not found
  4  API request failed
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def fetch_components(acli: str, project: str) -> list[str]:
    """Fetch component names through acli's authenticated project adapter."""
    try:
        result = subprocess.run(
            [acli, "jira", "project", "view", "--key", project, "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "acli returned no error detail")
        data = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, RuntimeError) as e:
        print(f"Error fetching {project} components: {e}", file=sys.stderr)
        sys.exit(4)
    return sorted(c["name"] for c in data.get("components", []) if c.get("name"))


def parse_component_section(fields_path: Path) -> set[str]:
    """Extract only components from the Component Catalog section."""
    text = fields_path.read_text(encoding="utf-8")
    components = set()
    in_catalog = False
    in_table = False

    for line in text.splitlines():
        if "### Component Catalog" in line:
            in_catalog = True
            continue
        if in_catalog and line.startswith("### "):
            # Hit next section
            in_catalog = False
            continue
        if not in_catalog:
            continue

        if line.startswith("|") and "---" in line:
            in_table = True
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 3 and cells[1] and cells[1] != "Component":
                components.add(cells[1])
        elif in_table and not line.startswith("|"):
            if line.strip() == "" or line.startswith("**"):
                in_table = False  # gap between tables, reset
            else:
                in_table = False

    return components


def main():
    parser = argparse.ArgumentParser(
        description="Validate fields.md components against live Jira data."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    # Find fields.md in the context skill that owns it
    script_dir = Path(__file__).resolve().parent
    fields_path = script_dir.parent.parent / "rhdh-jira-context" / "references" / "fields.md"
    if not fields_path.exists():
        print(f"fields.md not found at {fields_path}", file=sys.stderr)
        sys.exit(2)

    # Discover the authenticated adapter without inspecting its credential store.
    acli = shutil.which("acli")
    if not acli:
        print("acli not found. Run /setup-rhdh-skills jira.", file=sys.stderr)
        sys.exit(3)

    # Parse fields.md
    documented = parse_component_section(fields_path)

    # Fetch live components from both projects
    rhidp_components = set(fetch_components(acli, "RHIDP"))
    rhdhplan_components = set(fetch_components(acli, "RHDHPLAN"))
    live = rhidp_components | rhdhplan_components

    # Compare
    in_jira_not_doc = sorted(live - documented)
    in_doc_not_jira = sorted(documented - live)

    if args.json_output:
        result = {
            "documented_count": len(documented),
            "live_count": len(live),
            "missing_from_docs": in_jira_not_doc,
            "missing_from_jira": in_doc_not_jira,
            "in_sync": len(in_jira_not_doc) == 0 and len(in_doc_not_jira) == 0,
        }
        print(json.dumps(result, indent=2))
    else:
        print(f"Documented components: {len(documented)}")
        print(f"Live Jira components:  {len(live)}")
        print(f"  RHIDP:    {len(rhidp_components)}")
        print(f"  RHDHPLAN: {len(rhdhplan_components)}")
        print()

        if in_jira_not_doc:
            print(f"⚠️  In Jira but NOT in fields.md ({len(in_jira_not_doc)}):")
            for c in in_jira_not_doc:
                projects = []
                if c in rhidp_components:
                    projects.append("RHIDP")
                if c in rhdhplan_components:
                    projects.append("RHDHPLAN")
                print(f"  + {c}  ({', '.join(projects)})")
            print()

        if in_doc_not_jira:
            print(f"⚠️  In fields.md but NOT in Jira ({len(in_doc_not_jira)}):")
            for c in in_doc_not_jira:
                print(f"  - {c}")
            print()

        if not in_jira_not_doc and not in_doc_not_jira:
            print("✅ All components in sync.")
        else:
            print(
                f"❌ Drift detected: {len(in_jira_not_doc)} missing from docs, "
                f"{len(in_doc_not_jira)} missing from Jira."
            )

    sys.exit(0 if not in_jira_not_doc and not in_doc_not_jira else 1)


if __name__ == "__main__":
    main()
