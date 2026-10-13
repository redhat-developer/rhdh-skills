#!/usr/bin/env python3
"""Install the rhdh-spec-driven schema and config into a project's openspec/.

OpenSpec resolves schemas from the product repo's openspec/, not from this
skill directory. Callers run this once per project (setup or first OpenSpec
skill start) so `openspec new change --schema rhdh-spec-driven` and the
configured default both see Canonical Touchpoints and the sibling
specs/design graph.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONFIG = SKILL_ROOT / "config.yaml"
SOURCE_SCHEMA = SKILL_ROOT / "schemas" / "rhdh-spec-driven"


def fail(msg: str) -> int:
    sys.stderr.write(msg + ("\n" if not msg.endswith("\n") else ""))
    return 1


def install(project_root: Path, *, force: bool) -> int:
    if not SOURCE_CONFIG.is_file():
        return fail(f"Error: missing source config at {SOURCE_CONFIG}")
    if not SOURCE_SCHEMA.is_dir():
        return fail(f"Error: missing source schema at {SOURCE_SCHEMA}")

    root = project_root.resolve()
    openspec = root / "openspec"
    dest_config = openspec / "config.yaml"
    dest_schema = openspec / "schemas" / "rhdh-spec-driven"

    openspec.mkdir(parents=True, exist_ok=True)
    (openspec / "changes").mkdir(exist_ok=True)
    (openspec / "specs").mkdir(exist_ok=True)
    (openspec / "schemas").mkdir(exist_ok=True)

    actions: list[str] = []

    config_existed = dest_config.exists()
    if config_existed and not force:
        actions.append(f"kept {dest_config.relative_to(root)}")
    else:
        shutil.copy2(SOURCE_CONFIG, dest_config)
        verb = "replaced" if config_existed else "wrote"
        actions.append(f"{verb} {dest_config.relative_to(root)}")

    schema_existed = dest_schema.exists()
    if schema_existed and not force:
        actions.append(f"kept {dest_schema.relative_to(root)}/")
    else:
        if schema_existed:
            shutil.rmtree(dest_schema)
        shutil.copytree(SOURCE_SCHEMA, dest_schema)
        verb = "replaced" if schema_existed else "wrote"
        actions.append(f"{verb} {dest_schema.relative_to(root)}/")

    print(f"rhdh-spec-driven schema ready under {openspec.relative_to(root)}/")
    for line in actions:
        print(f"  {line}")
    print()
    print("Next: openspec schemas --json  # confirm rhdh-spec-driven is listed")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Copy config.yaml and schemas/rhdh-spec-driven into a project's openspec/."
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="Project root that should own openspec/ (default: cwd)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing config.yaml and schemas/rhdh-spec-driven/",
    )
    args = parser.parse_args(argv)
    root = Path(args.project_root)
    if not root.is_dir():
        return fail(f"Error: project root {root} is not a directory.")
    return install(root, force=args.force)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
