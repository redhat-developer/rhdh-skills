#!/usr/bin/env python3
"""Generate the ask-rhdh routing table from the skill catalog.

The routing table is a projection, not a source: the set of rows comes from the
catalog's model-invoked skills, and each row's text is that skill's own
`description` frontmatter. Hand-editing the table produced a second inventory
that drifted from the skills it claimed to describe, so the table
between the generated markers in SKILL.md is rewritten from those two sources.

    python scripts/render_routes.py            # print the table
    python scripts/render_routes.py --write    # rewrite the block in SKILL.md
    python scripts/render_routes.py --check    # exit 1 if SKILL.md is stale

Exit codes: 0 in sync or written, 1 stale under --check, 2 inputs unreadable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_DIR.parent.parent.parent
CATALOG_PATH = REPO_ROOT / "skills" / "meta" / "setup-rhdh-skills" / "assets" / "catalog.json"
SKILL_MD = SKILL_DIR / "SKILL.md"

BEGIN_MARKER = "<!-- BEGIN GENERATED ROUTES: python scripts/render_routes.py --write -->"
END_MARKER = "<!-- END GENERATED ROUTES -->"

HEADER = ["| When the request is | Model skill |", "|---|---|"]


def _fail(message: str) -> None:
    json.dump({"ok": False, "error": message}, sys.stdout, indent=2)
    print()
    sys.exit(2)


def read_description(skill_md: Path) -> str:
    """Return the frontmatter description as a single line.

    Handles both `description: text` and the folded `description: >-` form used
    by most skills. Deliberately not a YAML parser: skills are stdlib-only.
    """
    text = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"{skill_md} has no frontmatter block")

    lines = match.group(1).splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        inline = line[len("description:") :].strip()
        if inline and inline not in (">-", ">", "|-", "|"):
            return " ".join(inline.split())
        parts = []
        for continuation in lines[index + 1 :]:
            if continuation.strip() and not continuation.startswith((" ", "\t")):
                break
            parts.append(continuation.strip())
        return " ".join(" ".join(parts).split())
    raise ValueError(f"{skill_md} frontmatter has no description")


def build_rows() -> list[str]:
    """One row per model-invoked skill, in catalog order."""
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    rows = []
    for entry in catalog["skills"]:
        if entry.get("invocation") != "model":
            continue
        name = entry["name"]
        directory = entry.get("directory")
        skill_md = REPO_ROOT / "skills" / entry["category"]
        if directory:
            skill_md = skill_md / directory
        skill_md = skill_md / name / "SKILL.md"
        if not skill_md.is_file():
            raise FileNotFoundError(f"catalog names {name} but {skill_md} is missing")
        # Escape pipes (table cell separators) and asterisks (markdownlint's
        # MD037 reads `release-* ... task-*` as spaced emphasis and its --fix
        # hook would rewrite the generated table away from the catalog).
        description = read_description(skill_md).replace("|", "\\|").replace("*", "\\*")
        rows.append(f"| {description} | `/{name}` |")
    return rows


def render_table() -> str:
    return "\n".join(HEADER + build_rows())


def split_skill_md() -> tuple[str, str, str]:
    """Return the text before the block, the current block, and the text after."""
    text = SKILL_MD.read_text(encoding="utf-8")
    start = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        _fail(f"{SKILL_MD} is missing the generated-routes markers")
    body_start = start + len(BEGIN_MARKER)
    return text[:body_start], text[body_start:end].strip("\r\n"), text[end:]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="render_routes",
        description="Generate the ask-rhdh routing table from the skill catalog.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="rewrite the block in SKILL.md")
    mode.add_argument("--check", action="store_true", help="exit 1 if SKILL.md is stale")
    parser.add_argument("--json", action="store_true", help="structured output")
    args = parser.parse_args(argv)

    try:
        table = render_table()
    except (OSError, ValueError, KeyError) as error:
        _fail(str(error))
        return

    if not (args.write or args.check):
        if args.json:
            json.dump({"ok": True, "table": table}, sys.stdout, indent=2)
            print()
        else:
            print(table)
        return

    before, current, after = split_skill_md()
    in_sync = current == table

    if args.check:
        if args.json or not in_sync:
            json.dump(
                {"ok": in_sync, "path": str(SKILL_MD), "expected": table, "found": current},
                sys.stdout,
                indent=2,
            )
            print()
        sys.exit(0 if in_sync else 1)

    if not in_sync:
        SKILL_MD.write_text(f"{before}\n{table}\n{after}", encoding="utf-8")
    if args.json:
        json.dump(
            {"ok": True, "path": str(SKILL_MD), "rewritten": not in_sync}, sys.stdout, indent=2
        )
        print()


if __name__ == "__main__":
    main()
