#!/usr/bin/env python3
"""Generate `.claude-plugin/marketplace.json` from the skill catalog.

The marketplace file is a projection for `npx skills add` grouping, not a Claude
Code marketplace product and not a second inventory. Membership comes from
`catalog.json`. The `reference` category is editorial only: those skills are
folded into every installable category that `requiresSkills` them (transitively),
so selecting that category installs its support layer too.

    python scripts/generate_plugin_manifest.py            # print the JSON
    python scripts/generate_plugin_manifest.py --write    # rewrite marketplace.json
    python scripts/generate_plugin_manifest.py --check    # exit 1 if stale

Exit codes: 0 in sync or written, 1 stale under --check, 2 inputs unreadable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "skills" / "meta" / "setup-rhdh-skills" / "assets" / "catalog.json"
MANIFEST_PATH = REPO_ROOT / ".claude-plugin" / "marketplace.json"

# Editorial category that must not appear as an installer group. Its skills ship
# as dependencies of the installable categories that require them.
HIDDEN_INSTALL_CATEGORIES = frozenset({"reference"})

# The third-party category installs as one selectable group per upstream
# source directory, so a consumer can pick mattpocock-skills without every
# other vendor's skills (ADR-0011).
THIRD_PARTY_CATEGORY = "third-party"

# skills CLI title-cases each kebab segment; spell acronyms so the tree reads
# "CI" rather than "Ci".
PLUGIN_NAME_BY_CATEGORY = {
    "ci": "CI",
}


def _fail(message: str) -> None:
    json.dump({"ok": False, "error": message}, sys.stdout, indent=2)
    print()
    sys.exit(2)


def plugin_name(category: str) -> str:
    return PLUGIN_NAME_BY_CATEGORY.get(category, category)


def plugin_description(category: str) -> str:
    name = plugin_name(category)
    label = name if category in PLUGIN_NAME_BY_CATEGORY else name[:1].upper() + name[1:]
    return f"{label} skills from the RHDH pack"


def _skill_path(entry: dict[str, Any]) -> str:
    directory = entry.get("directory")
    skill = f"{directory}/{entry['name']}" if directory else entry["name"]
    return f"./skills/{entry['category']}/{skill}"


def _reference_closure(
    skill_name: str,
    by_name: dict[str, dict[str, Any]],
    visiting: set[str] | None = None,
) -> list[str]:
    """Return reference-skill paths required by ``skill_name``, dependents first.

    Walks ``requiresSkills`` only (not ``optionalSkills``). Non-reference
    dependencies are followed when they themselves require reference skills.
    """
    if visiting is None:
        visiting = set()
    if skill_name in visiting:
        raise ValueError(f"requiresSkills cycle involving {skill_name}")
    visiting.add(skill_name)

    entry = by_name.get(skill_name)
    if entry is None:
        raise ValueError(f"requiresSkills names unknown skill {skill_name!r}")

    ordered: list[str] = []
    seen: set[str] = set()
    for dependency in entry.get("requiresSkills") or []:
        if not isinstance(dependency, str):
            raise ValueError(f"{skill_name}: requiresSkills entries must be strings")
        dep_entry = by_name.get(dependency)
        if dep_entry is None:
            raise ValueError(f"{skill_name}: requiresSkills names unknown skill {dependency!r}")
        for path in _reference_closure(dependency, by_name, visiting):
            if path not in seen:
                seen.add(path)
                ordered.append(path)
        if dep_entry.get("category") in HIDDEN_INSTALL_CATEGORIES:
            path = _skill_path(dep_entry)
            if path not in seen:
                seen.add(path)
                ordered.append(path)

    visiting.remove(skill_name)
    return ordered


def build_manifest(catalog: dict[str, Any]) -> dict[str, Any]:
    """One marketplace plugin per installable category, with reference deps folded in."""
    categories = catalog.get("categories")
    skills = catalog.get("skills")
    pack = catalog.get("pack") or {}
    if not isinstance(categories, list) or not categories:
        raise ValueError("catalog.json has no categories list")
    if not isinstance(skills, list):
        raise ValueError("catalog.json has no skills list")

    by_name: dict[str, dict[str, Any]] = {}
    by_category: dict[str, list[dict[str, Any]]] = {category: [] for category in categories}
    for entry in skills:
        name = entry.get("name")
        category = entry.get("category")
        if not isinstance(name, str) or not isinstance(category, str):
            raise ValueError(f"catalog skill entry missing name/category: {entry!r}")
        if category not in by_category:
            raise ValueError(f"{name}: category {category!r} is not in catalog categories")
        if name in by_name:
            raise ValueError(f"duplicate catalog skill name {name!r}")
        by_name[name] = entry
        by_category[category].append(entry)

    installable = [category for category in categories if category not in HIDDEN_INSTALL_CATEGORIES]
    if not installable:
        raise ValueError("catalog.json has no installable categories")

    plugins = []
    for category in installable:
        entries = by_category[category]
        if not entries:
            raise ValueError(f"category {category!r} has no skills in the catalog")

        if category == THIRD_PARTY_CATEGORY:
            directories: list[str] = []
            by_directory: dict[str, list[dict[str, Any]]] = {}
            for entry in entries:
                directory = entry.get("directory")
                if not isinstance(directory, str) or not directory:
                    raise ValueError(f"{entry['name']}: third-party skills must carry a directory")
                if directory not in by_directory:
                    by_directory[directory] = []
                    directories.append(directory)
                by_directory[directory].append(entry)
            for directory in directories:
                plugins.append(
                    {
                        "name": directory,
                        "source": "./",
                        "description": f"Third-party skills vendored from {directory}",
                        "skills": [_skill_path(entry) for entry in by_directory[directory]],
                    }
                )
            continue

        paths: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            own = _skill_path(entry)
            if own not in seen:
                seen.add(own)
                paths.append(own)
            for path in _reference_closure(entry["name"], by_name):
                if path not in seen:
                    seen.add(path)
                    paths.append(path)

        plugins.append(
            {
                "name": plugin_name(category),
                "source": "./",
                "description": plugin_description(category),
                "skills": paths,
            }
        )

    # skills CLI: last plugin that lists a path wins pluginName. Put earlier
    # installable categories last so shared reference skills stay in those groups.
    plugins.reverse()

    source = pack.get("source") or "redhat-developer/rhdh-skills"
    return {
        "name": "rhdh-skills",
        "owner": {
            "name": "Red Hat Developer Hub",
            "url": f"https://github.com/{source}",
        },
        "description": (
            "Projection of the promoted RHDH skill catalog for npx skills "
            "installer grouping. Not a Claude Code marketplace product. "
            "Reference skills are folded into each installable category that "
            "requires them."
        ),
        "plugins": plugins,
    }


def render_manifest() -> str:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return json.dumps(build_manifest(catalog), indent=2) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="generate_plugin_manifest",
        description="Generate .claude-plugin/marketplace.json from the skill catalog.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="rewrite marketplace.json")
    mode.add_argument("--check", action="store_true", help="exit 1 if marketplace.json is stale")
    parser.add_argument("--json", action="store_true", help="structured output")
    args = parser.parse_args(argv)

    try:
        rendered = render_manifest()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        _fail(str(error))
        return

    if not (args.write or args.check):
        if args.json:
            json.dump({"ok": True, "manifest": json.loads(rendered)}, sys.stdout, indent=2)
            print()
        else:
            sys.stdout.write(rendered)
        return

    current = MANIFEST_PATH.read_text(encoding="utf-8") if MANIFEST_PATH.is_file() else ""
    in_sync = current == rendered

    if args.check:
        if args.json or not in_sync:
            json.dump(
                {
                    "ok": in_sync,
                    "path": str(MANIFEST_PATH),
                    "expected": rendered,
                    "found": current,
                },
                sys.stdout,
                indent=2,
            )
            print()
        sys.exit(0 if in_sync else 1)

    if not in_sync:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(rendered, encoding="utf-8")
    if args.json:
        json.dump(
            {"ok": True, "path": str(MANIFEST_PATH), "rewritten": not in_sync},
            sys.stdout,
            indent=2,
        )
        print()


if __name__ == "__main__":
    main()
