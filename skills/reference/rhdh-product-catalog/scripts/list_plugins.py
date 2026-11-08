#!/usr/bin/env python3
"""List RHDH Extensions catalog Plugin YAML for a release.

Reads catalog-entities/extensions/plugins/*.yaml from
rhdh-plugin-export-overlays. Does not check out or otherwise mutate a local
working tree.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_SKILL_ROOT = Path(__file__).resolve().parents[1]
_LIB = _SKILL_ROOT / "scripts" / "lib"
_SCRIPTS = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import list_packages as lp_packages  # noqa: E402
from default_packages import (  # noqa: E402
    DEFAULT_PACKAGES_REL,
    DEFAULT_PACKAGES_URL,
    CoreIndex,
    enrich_plugins_with_core,
    plugin_package_refs,
)
from diff import (  # noqa: E402
    DiffReport,
    arrow,
    diff_items,
    plugin_key,
    restrict_to_matching_identities,
)
from overlay_repo import (  # noqa: E402
    collect_overlay,
    collect_overlay_pair,
    ensure_git_ref,
    list_via_git,
    load_core_index,
    read_files_via_git,
    version_to_ref,
)
from support import (  # noqa: E402
    SUPPORT_LABELS,
    SUPPORT_ORDER,
    as_str,
    md_cell,
    normalize_support,
    resolve_support_filters,
    source_caption,
    source_caption_diff,
)
from support_alignment import (  # noqa: E402
    alignment_payload,
    analyze_support_alignment,
    render_alignment_markdown,
)
from yaml_lite import parse_yaml  # noqa: E402

PLUGIN_PATH = re.compile(r"^catalog-entities/extensions/plugins/([^/]+)\.ya?ml$")
PREINSTALLED_ANN = "extensions.backstage.io/pre-installed"
ALL_YAML_REL = "catalog-entities/extensions/plugins/all.yaml"
IN_CATALOG = "in-catalog"
PACKAGED = "packaged"
MEMBERSHIP_LABELS = {
    IN_CATALOG: "Included in the Catalog",
    PACKAGED: "Packaged, but Not in Catalog",
}
MEMBERSHIP_ORDER = (IN_CATALOG, PACKAGED)
USAGE_EXIT = 2
RESOLVE_EXIT = 3
EMPTY_EXIT = 1

# Notes from the last all.yaml parse (CLI is single-threaded).
_load_notes: list[str] = []


def is_plugin_path(rel_path: str) -> bool:
    """True for Plugin YAML rows. Skip all.yaml and boilerplate samples."""
    rel = rel_path.replace("\\", "/")
    base = Path(rel).name
    if base == "all.yaml" or base.endswith(".sample"):
        return False
    return bool(PLUGIN_PATH.match(rel))


def catalog_targets_from_all_yaml(text: str) -> set[str]:
    """Filenames listed in all.yaml spec.targets (default-install catalog)."""
    doc = parse_yaml(text)
    targets = (doc.get("spec") or {}).get("targets") or []
    names: set[str] = set()
    if not isinstance(targets, list):
        return names
    for item in targets:
        name = as_str(item).lstrip("./")
        if not name or name == "all.yaml" or name.endswith(".sample"):
            continue
        names.add(Path(name).name)
    return names


def apply_catalog_membership(
    plugins: list[dict[str, Any]],
    targets: set[str],
    *,
    all_yaml_found: bool,
) -> list[str]:
    notes: list[str] = []
    if not all_yaml_found:
        notes.append(
            "catalog-entities/extensions/plugins/all.yaml was not found; "
            "treating every plugin as Packaged, but Not in Catalog."
        )
    present = {Path(p["file"]).name for p in plugins}
    missing = sorted(targets - present)
    if missing:
        preview = ", ".join(missing[:8])
        extra = f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
        notes.append(
            f"all.yaml lists {len(missing)} plugin file(s) with no Plugin YAML: {preview}{extra}."
        )
    for plugin in plugins:
        name = Path(plugin["file"]).name
        in_catalog = name in targets
        plugin["in_catalog"] = in_catalog
        plugin["catalog_membership"] = IN_CATALOG if in_catalog else PACKAGED
        plugin["catalog_membership_label"] = MEMBERSHIP_LABELS[plugin["catalog_membership"]]
    return notes


def is_preinstalled(meta: dict[str, Any]) -> bool:
    annotations = meta.get("annotations") or {}
    if not isinstance(annotations, dict):
        return False
    raw = annotations.get(PREINSTALLED_ANN)
    if raw is True:
        return True
    return as_str(raw).lower() in {"true", "yes", "1"}


def support_provider(raw: Any) -> str:
    if isinstance(raw, dict):
        return as_str(raw.get("provider"))
    return ""


def extract_plugin(doc: dict[str, Any], rel_path: str) -> dict[str, Any]:
    meta = doc.get("metadata") or {}
    spec = doc.get("spec") or {}
    support_raw = spec.get("support")
    support_key = normalize_support(support_raw)
    title = as_str(meta.get("title")) or as_str(meta.get("name"))
    preinstalled = is_preinstalled(meta)
    return {
        "file": rel_path,
        "kind": as_str(doc.get("kind")),
        "name": as_str(meta.get("name")),
        "title": title,
        "support": support_key,
        "support_label": SUPPORT_LABELS[support_key],
        "lifecycle": as_str(spec.get("lifecycle")),
        "author": as_str(spec.get("author")),
        "provider": support_provider(support_raw),
        "publisher": as_str(spec.get("publisher")),
        "preinstalled": preinstalled,
        "catalog_yaml": "pre-installed" if preinstalled else "custom",
        "in_catalog": False,
        "catalog_membership": PACKAGED,
        "catalog_membership_label": MEMBERSHIP_LABELS[PACKAGED],
        "support_raw": support_raw,
        "package_refs": [],
        "npm_packages": [],
        "core": False,
        "core_ootb": "",
        "core_ootb_label": "",
    }


def load_plugin_from_text(rel_path: str, text: str) -> dict[str, Any] | None:
    if not is_plugin_path(rel_path):
        return None
    try:
        doc = parse_yaml(text)
    except Exception as exc:
        return {
            "file": rel_path,
            "kind": "",
            "name": "",
            "title": rel_path,
            "support": "unknown",
            "support_label": SUPPORT_LABELS["unknown"],
            "lifecycle": "",
            "author": "",
            "provider": "",
            "publisher": "",
            "preinstalled": False,
            "catalog_yaml": "custom",
            "in_catalog": False,
            "catalog_membership": PACKAGED,
            "catalog_membership_label": MEMBERSHIP_LABELS[PACKAGED],
            "parse_error": str(exc),
            "package_refs": [],
            "npm_packages": [],
            "core": False,
            "core_ootb": "",
            "core_ootb_label": "",
        }
    if as_str(doc.get("kind")) != "Plugin":
        return None
    plugin = extract_plugin(doc, rel_path)
    if plugin:
        plugin["package_refs"] = plugin_package_refs(doc, text)
    return plugin


def list_plugin_files_on_disk(root: Path) -> list[Path]:
    folder = root / "catalog-entities" / "extensions" / "plugins"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix in {".yaml", ".yml"})


def load_from_workdir(root: Path) -> list[dict[str, Any]]:
    global _load_notes
    plugins: list[dict[str, Any]] = []
    for path in list_plugin_files_on_disk(root):
        rel = path.relative_to(root).as_posix()
        plugin = load_plugin_from_text(rel, path.read_text(encoding="utf-8"))
        if plugin:
            plugins.append(plugin)
    all_path = root / ALL_YAML_REL
    if all_path.is_file():
        targets = catalog_targets_from_all_yaml(all_path.read_text(encoding="utf-8"))
        _load_notes = apply_catalog_membership(plugins, targets, all_yaml_found=True)
    else:
        _load_notes = apply_catalog_membership(plugins, set(), all_yaml_found=False)
    return plugins


def load_from_git(repo: Path, ref: str) -> tuple[list[dict[str, Any]], str]:
    global _load_notes
    resolved = ensure_git_ref(repo, ref)
    rels: list[str] = []
    for rel in list_via_git(repo, resolved, "catalog-entities/extensions/plugins"):
        posix = rel.replace("\\", "/")
        if posix.endswith(".sample"):
            continue
        rels.append(rel)
    texts = read_files_via_git(repo, resolved, rels)
    plugins: list[dict[str, Any]] = []
    all_text: str | None = None
    for rel in rels:
        text = texts.get(rel)
        if text is None:
            continue
        posix = rel.replace("\\", "/")
        if posix.endswith("/all.yaml") or posix == ALL_YAML_REL:
            all_text = text
            continue
        plugin = load_plugin_from_text(rel, text)
        if plugin:
            plugins.append(plugin)
    if all_text is not None:
        targets = catalog_targets_from_all_yaml(all_text)
        _load_notes = apply_catalog_membership(plugins, targets, all_yaml_found=True)
    else:
        _load_notes = apply_catalog_membership(plugins, set(), all_yaml_found=False)
    return plugins, resolved


def matches_filters(
    plugin: dict[str, Any],
    *,
    supports: set[str],
    catalog_yaml: set[str],
    membership: set[str],
    names: list[str],
    lifecycles: list[str],
    core_only: bool = False,
    ootb_enabled: bool = False,
    ootb_disabled: bool = False,
) -> bool:
    if supports and plugin["support"] not in supports:
        return False
    if core_only and not plugin.get("core"):
        return False
    if ootb_enabled and plugin.get("core_ootb") != "enabled":
        return False
    if ootb_disabled and plugin.get("core_ootb") != "disabled":
        return False
    if catalog_yaml and plugin["catalog_yaml"] not in catalog_yaml:
        return False
    if membership and plugin["catalog_membership"] not in membership:
        return False
    if names:
        hay = " ".join(
            [plugin.get("title", ""), plugin.get("name", ""), plugin.get("file", "")]
        ).lower()
        if not any(n.lower() in hay for n in names):
            return False
    if lifecycles:
        life = plugin.get("lifecycle", "").lower()
        if life not in {x.lower() for x in lifecycles}:
            return False
    return True


def sort_plugins(plugins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    support_rank = {key: i for i, key in enumerate(SUPPORT_ORDER)}
    membership_rank = {key: i for i, key in enumerate(MEMBERSHIP_ORDER)}

    def key(plugin: dict[str, Any]) -> tuple:
        return (
            membership_rank.get(plugin.get("catalog_membership"), len(MEMBERSHIP_ORDER)),
            support_rank.get(plugin["support"], len(SUPPORT_ORDER)),
            plugin["title"].lower(),
            plugin.get("name", "").lower(),
        )

    return sorted(plugins, key=key)


def group_by_membership_and_support(
    plugins: list[dict[str, Any]],
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """[(membership_key, support_key, plugins), ...] in display order."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for plugin in plugins:
        key = (plugin.get("catalog_membership", PACKAGED), plugin["support"])
        buckets.setdefault(key, []).append(plugin)
    grouped: list[tuple[str, str, list[dict[str, Any]]]] = []
    for membership in MEMBERSHIP_ORDER:
        for support in SUPPORT_ORDER:
            rows = buckets.get((membership, support))
            if rows:
                grouped.append((membership, support, rows))
    return grouped


def core_cell(plugin: dict[str, Any]) -> str:
    if not plugin.get("core"):
        return "—"
    return md_cell(plugin.get("core_ootb_label") or plugin.get("core_ootb", ""))


def render_markdown(
    *,
    version: str,
    ref: str,
    source: dict[str, str],
    plugins: list[dict[str, Any]],
    warnings: list[str],
    filtered: bool,
    scanned: int,
    core_index: CoreIndex | None = None,
) -> str:
    support_counts = Counter(p["support"] for p in plugins)
    yaml_counts = Counter(p["catalog_yaml"] for p in plugins)
    membership_counts = Counter(p.get("catalog_membership") for p in plugins)
    lines: list[str] = [
        f"# RHDH {version} plugins (`{ref}`)",
        "",
        f"**{len(plugins)} plugin{'s' if len(plugins) != 1 else ''}**"
        + (" (filtered)" if filtered else ""),
        "",
        f"_Source: {source_caption(source, ref)}_",
        "",
        "| Default catalog | Count |",
        "|---|---|",
        f"| {MEMBERSHIP_LABELS[IN_CATALOG]} | {membership_counts.get(IN_CATALOG, 0)} |",
        f"| {MEMBERSHIP_LABELS[PACKAGED]} | {membership_counts.get(PACKAGED, 0)} |",
        "",
        "| Support level | Count |",
        "|---|---|",
    ]
    for key in SUPPORT_ORDER:
        count = support_counts.get(key, 0)
        if key == "unknown" and count == 0:
            continue
        lines.append(f"| {SUPPORT_LABELS[key]} | {count} |")
    if core_index:
        core_counts = Counter(p.get("core_ootb") for p in plugins if p.get("core"))
        lines.extend(
            [
                "",
                f"| Core ([default.packages.yaml]({DEFAULT_PACKAGES_URL})) | Count |",
                "|---|---|",
                f"| enabled OOTB | {core_counts.get('enabled', 0)} |",
                f"| disabled OOTB | {core_counts.get('disabled', 0)} |",
                f"| mixed OOTB | {core_counts.get('mixed', 0)} |",
                f"| not core | {sum(1 for p in plugins if not p.get('core'))} |",
            ]
        )
    lines.extend(
        [
            "",
            "| Plugin YAML annotation | Count |",
            "|---|---|",
            f"| pre-installed | {yaml_counts.get('pre-installed', 0)} |",
            f"| custom | {yaml_counts.get('custom', 0)} |",
            "",
            f"Scanned {scanned} Plugin YAML files on `{ref}` (skipped all.yaml and *.sample).",
        ]
    )
    if warnings:
        lines.append("")
        for warning in warnings:
            lines.append(f"> {warning}")
    last_membership: str | None = None
    for membership, support, group in group_by_membership_and_support(plugins):
        if membership != last_membership:
            lines.extend(["", f"## {MEMBERSHIP_LABELS[membership]}"])
            last_membership = membership
        lines.extend(
            [
                "",
                f"### {SUPPORT_LABELS[support]}",
                "",
                "| Title | Support | Lifecycle | Author | Provider | Publisher | Core OOTB | Plugin YAML |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for plugin in group:
            lines.append(
                "| "
                + " | ".join(
                    [
                        md_cell(plugin["title"]),
                        md_cell(plugin["support_label"]),
                        md_cell(plugin["lifecycle"]),
                        md_cell(plugin["author"]),
                        md_cell(plugin["provider"]),
                        md_cell(plugin["publisher"]),
                        core_cell(plugin),
                        md_cell(plugin["catalog_yaml"]),
                    ]
                )
                + " |"
            )
    lines.append("")
    return "\n".join(lines)


def _plugin_row_cells(plugin: dict[str, Any]) -> list[str]:
    return [
        md_cell(plugin["title"]),
        md_cell(plugin["support_label"]),
        md_cell(plugin["lifecycle"]),
        md_cell(plugin["author"]),
        md_cell(plugin["provider"]),
        md_cell(plugin["publisher"]),
        core_cell(plugin),
        md_cell(plugin["catalog_yaml"]),
        md_cell(plugin.get("catalog_membership_label", "")),
    ]


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


_PLUGIN_SNAPSHOT_HEADERS = [
    "Title",
    "Support",
    "Lifecycle",
    "Author",
    "Provider",
    "Publisher",
    "Core OOTB",
    "Plugin YAML",
    "Catalog",
]


def render_diff_markdown(
    *,
    version_from: str,
    ref_from: str,
    version_to: str,
    ref_to: str,
    source: dict[str, str],
    report: DiffReport,
    warnings: list[str],
    filtered: bool,
    scanned_from: int,
    scanned_to: int,
) -> str:
    support_rows = report.support_changes()
    lifecycle_rows = report.lifecycle_changes()
    lines: list[str] = [
        f"# RHDH plugin diff: {version_from} → {version_to} (`{ref_from}` → `{ref_to}`)",
        "",
        f"_Source: {source_caption_diff(source, ref_from, ref_to)}_",
        "",
        f"Scanned {scanned_from} Plugin YAML files on `{ref_from}` and "
        f"{scanned_to} on `{ref_to}`"
        + (" (filtered)" if filtered else "")
        + " (skipped all.yaml and *.sample).",
        "",
        "| Change | Count |",
        "|---|---|",
        f"| Support level | {len(support_rows)} |",
        f"| Newly added | {len(report.added)} |",
        f"| Lifecycle | {len(lifecycle_rows)} |",
        f"| Removed | {len(report.removed)} |",
        f"| Unchanged | {report.unchanged} |",
    ]
    if warnings:
        lines.append("")
        for warning in warnings:
            lines.append(f"> {warning}")

    def section(title: str, body: list[str]) -> None:
        lines.extend(["", f"## {title}", ""])
        lines.extend(body)

    if support_rows:
        section(
            "Support level changed",
            _md_table(
                ["Title", "Name", "Support"],
                [
                    [
                        md_cell(row["to"]["title"]),
                        md_cell(row["to"]["name"]),
                        arrow(row["from"]["support_label"], row["to"]["support_label"]),
                    ]
                    for row in support_rows
                ],
            ),
        )
    if report.added:
        section(
            f"Newly added (in {version_to}, not in {version_from})",
            _md_table(
                _PLUGIN_SNAPSHOT_HEADERS,
                [_plugin_row_cells(plugin) for plugin in report.added],
            ),
        )
    if lifecycle_rows:
        section(
            "Lifecycle changed",
            _md_table(
                ["Title", "Name", "Lifecycle"],
                [
                    [
                        md_cell(row["to"]["title"]),
                        md_cell(row["to"]["name"]),
                        arrow(row["from"]["lifecycle"], row["to"]["lifecycle"]),
                    ]
                    for row in lifecycle_rows
                ],
            ),
        )
    if report.removed:
        section(
            f"Removed (in {version_from}, not in {version_to})",
            _md_table(
                _PLUGIN_SNAPSHOT_HEADERS,
                [_plugin_row_cells(plugin) for plugin in report.removed],
            ),
        )
    if not (support_rows or report.added or lifecycle_rows or report.removed):
        lines.extend(
            [
                "",
                f"No support, lifecycle, added, or removed plugin changes "
                f"between {version_from} and {version_to}.",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def build_warnings(plugins: list[dict[str, Any]], scanned: int) -> list[str]:
    warnings: list[str] = []
    unknown = [p for p in plugins if p["support"] == "unknown"]
    if unknown:
        warnings.append(
            f"{len(unknown)} plugin(s) have missing or unrecognized spec.support.level "
            "(listed as Unknown, last)."
        )
    parse_errors = [p for p in plugins if p.get("parse_error")]
    if parse_errors:
        warnings.append(f"{len(parse_errors)} metadata file(s) failed to parse.")
    if scanned == 0:
        warnings.append("No Plugin entities found in catalog-entities/extensions/plugins.")
    return warnings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "List RHDH Extensions catalog plugins from overlay Plugin YAML, "
            "grouped by default-catalog membership then decreasing support level. "
            "Use --diff FROM TO to compare two versions. "
            "Use --support-alignment to flag plugin vs package support mismatches."
        )
    )
    parser.add_argument(
        "version",
        nargs="?",
        help="RHDH version or overlay git ref (1.10, 1.10.3, main, release-1.10)",
    )
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("FROM", "TO"),
        help="Compare two versions: support-level changes, newly added, lifecycle changes, removed",
    )
    parser.add_argument(
        "--repo",
        help="Path to a local rhdh-plugin-export-overlays checkout",
    )
    parser.add_argument(
        "--ref",
        help="Override git ref (default: mapped from version). Ignored for non-git --repo trees.",
    )
    parser.add_argument(
        "--workdir",
        action="store_true",
        help="Read metadata from the working tree of --repo instead of git show",
    )
    parser.add_argument(
        "--support",
        action="append",
        default=[],
        help="Filter by support level (repeatable). Aliases: ga, tp, dp, community",
    )
    parser.add_argument(
        "--in-catalog",
        action="store_true",
        help="Only plugins listed in all.yaml (default-install Extensions catalog)",
    )
    parser.add_argument(
        "--not-in-catalog",
        action="store_true",
        help="Only packaged Plugin YAML files that are not listed in all.yaml",
    )
    parser.add_argument(
        "--pre-installed",
        action="store_true",
        help="Only plugins whose YAML annotation is pre-installed",
    )
    parser.add_argument(
        "--custom",
        action="store_true",
        help="Only plugins whose YAML annotation is custom (not pre-installed)",
    )
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        help="Filter by title or metadata.name substring (repeatable)",
    )
    parser.add_argument(
        "--lifecycle",
        action="append",
        default=[],
        help="Filter by spec.lifecycle (repeatable, case-insensitive)",
    )
    parser.add_argument(
        "--core",
        action="store_true",
        help="Only plugins whose packages appear in default.packages.yaml",
    )
    parser.add_argument(
        "--enabled-ootb",
        action="store_true",
        help="Only core plugins with all core packages enabled OOTB",
    )
    parser.add_argument(
        "--disabled-ootb",
        action="store_true",
        help="Only core plugins with all core packages disabled OOTB",
    )
    parser.add_argument(
        "--support-alignment",
        action="store_true",
        help=(
            "Flag support-level differences between Plugin catalog entities and "
            "linked Package metadata for manual review"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of markdown")
    return parser.parse_args(argv)


def catalog_yaml_filter(pre_installed: bool, custom: bool) -> set[str]:
    if pre_installed and not custom:
        return {"pre-installed"}
    if custom and not pre_installed:
        return {"custom"}
    return set()


def membership_filter(in_catalog: bool, not_in_catalog: bool) -> set[str]:
    if in_catalog and not not_in_catalog:
        return {IN_CATALOG}
    if not_in_catalog and not in_catalog:
        return {PACKAGED}
    return set()


def repo_for_core(source: dict[str, str], repo_arg: str | None) -> Path | None:
    stype = source.get("type")
    if stype in ("local-git", "clone"):
        return Path(source["path"])
    if repo_arg:
        repo = Path(repo_arg).expanduser().resolve()
        if (repo / ".git").is_dir():
            return repo
    return None


def note_missing_core(core_index: CoreIndex | None, ref: str, warnings: list[str]) -> None:
    if core_index is None:
        warnings.append(
            f"`{DEFAULT_PACKAGES_REL}` not found on `{ref}`; Core OOTB column is blank. "
            f"See {DEFAULT_PACKAGES_URL}"
        )


def load_package_rows(
    source: dict[str, str],
    repo_arg: str | None,
    ref: str,
    *,
    workdir: bool,
) -> list[dict[str, Any]]:
    root = Path(source["path"])
    if workdir or source.get("type") in {"workdir", "clone"}:
        return lp_packages.load_from_workdir(root)
    repo = repo_for_core(source, repo_arg)
    if repo:
        rows, _ = lp_packages.load_from_git(repo, ref)
        return rows
    return []


def apply_plugin_core(
    plugins: list[dict[str, Any]],
    *,
    source: dict[str, str],
    repo_arg: str | None,
    ref: str,
    workdir: bool,
) -> CoreIndex | None:
    core_index = load_core_index(repo_for_core(source, repo_arg), ref, source)
    package_rows = load_package_rows(source, repo_arg, ref, workdir=workdir)
    enrich_plugins_with_core(plugins, core=core_index, packages=package_rows)
    return core_index


def _emit(payload: dict[str, Any], markdown: str, as_json: bool) -> None:
    if as_json:
        json.dump(payload, sys.stdout, indent=2 if sys.stdout.isatty() else None)
        if sys.stdout.isatty():
            sys.stdout.write("\n")
    else:
        sys.stdout.write(markdown)


def _diff_payload(
    *,
    version_from: str,
    ref_from: str,
    version_to: str,
    ref_to: str,
    source: dict[str, str],
    report: DiffReport,
    warnings: list[str],
    filtered: bool,
    scanned_from: int,
    scanned_to: int,
) -> dict[str, Any]:
    return {
        "mode": "diff",
        "from": {"version": version_from, "ref": ref_from, "scanned": scanned_from},
        "to": {"version": version_to, "ref": ref_to, "scanned": scanned_to},
        "source": source,
        "filtered": filtered,
        "counts": {
            "support": len(report.support_changes()),
            "added": len(report.added),
            "lifecycle": len(report.lifecycle_changes()),
            "removed": len(report.removed),
            "unchanged": report.unchanged,
        },
        "warnings": warnings,
        "added": report.added,
        "removed": report.removed,
        "support": report.support_changes(),
        "lifecycle": report.lifecycle_changes(),
        "changed": report.changed,
    }


def validate_args(args: argparse.Namespace) -> str | None:
    if args.diff and args.support_alignment:
        return "--support-alignment cannot be used with --diff."
    if args.support_alignment:
        if not args.version:
            return "A version is required with --support-alignment."
        return None
    if args.diff:
        if args.version:
            return "Do not pass a positional version with --diff; use --diff FROM TO."
        if args.workdir:
            return "--workdir cannot be used with --diff (both versions are read with git show)."
        if args.ref:
            return "--ref cannot be used with --diff (each version maps to its own git ref)."
        return None
    if not args.version:
        return "A version is required, or pass --diff FROM TO."
    return None


def _prefix_notes(version: str, notes: list[str]) -> list[str]:
    return [f"{version}: {note}" for note in notes]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    usage = validate_args(args)
    if usage:
        print(usage, file=sys.stderr)
        return USAGE_EXIT
    try:
        support_filters = resolve_support_filters(args.support)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE_EXIT

    catalog_yaml = catalog_yaml_filter(args.pre_installed, args.custom)
    membership = membership_filter(args.in_catalog, args.not_in_catalog)
    temp_dir = None
    try:
        if args.support_alignment:
            if (
                support_filters
                or catalog_yaml
                or membership
                or args.name
                or args.lifecycle
                or args.core
                or args.enabled_ootb
                or args.disabled_ootb
            ):
                print("note: list filters are ignored with --support-alignment.", file=sys.stderr)
            try:
                plugins, ref, source, temp_dir = collect_overlay(
                    version=args.version,
                    repo_arg=args.repo,
                    ref_arg=args.ref,
                    workdir=args.workdir,
                    temp_prefix="rhdh-product-catalog-plugins-",
                    load_workdir=load_from_workdir,
                    load_git=load_from_git,
                )
            except FileNotFoundError as exc:
                print(str(exc), file=sys.stderr)
                return RESOLVE_EXIT
            except subprocess.CalledProcessError as exc:
                err = (exc.stderr or exc.stdout or str(exc)).strip()
                print(err, file=sys.stderr)
                return RESOLVE_EXIT

            package_rows = load_package_rows(source, args.repo, ref, workdir=args.workdir)
            warnings = list(_load_notes) + build_warnings(plugins, len(plugins))
            report = analyze_support_alignment(plugins, package_rows)
            payload = alignment_payload(
                version=args.version,
                ref=ref,
                source=source,
                report=report,
                warnings=warnings,
            )
            _emit(
                payload,
                render_alignment_markdown(
                    version=args.version,
                    ref=ref,
                    source_caption=source_caption(source, ref),
                    report=report,
                    warnings=warnings,
                ),
                args.json,
            )
            if len(plugins) == 0 and len(package_rows) == 0:
                return EMPTY_EXIT
            return 0

        if args.diff:
            version_from, version_to = args.diff
            ignored = []
            if support_filters:
                ignored.append("--support")
            if catalog_yaml:
                ignored.append("--pre-installed/--custom")
            if membership:
                ignored.append("--in-catalog/--not-in-catalog")
            if args.lifecycle:
                ignored.append("--lifecycle")
            if ignored:
                print(
                    "note: "
                    + ", ".join(ignored)
                    + " ignored with --diff (those fields are compared, not used as snapshot filters).",
                    file=sys.stderr,
                )
            notes_from: list[str] = []
            notes_to: list[str] = []
            load_count = 0

            def capture_notes() -> None:
                nonlocal load_count
                notes = list(_load_notes)
                if load_count == 0:
                    notes_from.extend(notes)
                else:
                    notes_to.extend(notes)
                load_count += 1

            def load_git_pair(repo: Path, ref: str) -> tuple[list[dict[str, Any]], str]:
                rows, resolved = load_from_git(repo, ref)
                capture_notes()
                return rows, resolved

            def load_workdir_pair(root: Path) -> list[dict[str, Any]]:
                rows = load_from_workdir(root)
                capture_notes()
                return rows

            try:
                from_plugins, ref_from, to_plugins, ref_to, source, temp_dir = collect_overlay_pair(
                    version_from=version_from,
                    version_to=version_to,
                    repo_arg=args.repo,
                    temp_prefix="rhdh-product-catalog-plugins-",
                    load_git=load_git_pair,
                    load_workdir=load_workdir_pair,
                )
            except FileNotFoundError as exc:
                print(str(exc), file=sys.stderr)
                return RESOLVE_EXIT
            except subprocess.CalledProcessError as exc:
                err = (exc.stderr or exc.stdout or str(exc)).strip()
                print(err, file=sys.stderr)
                return RESOLVE_EXIT

            scanned_from = len(from_plugins)
            scanned_to = len(to_plugins)
            ref_from = version_to_ref(version_from)
            ref_to = version_to_ref(version_to)
            core_from = apply_plugin_core(
                from_plugins,
                source=source,
                repo_arg=args.repo,
                ref=ref_from,
                workdir=False,
            )
            core_to = apply_plugin_core(
                to_plugins,
                source=source,
                repo_arg=args.repo,
                ref=ref_to,
                workdir=False,
            )
            identity = bool(args.name)
            if identity:
                from_plugins, to_plugins = restrict_to_matching_identities(
                    from_plugins,
                    to_plugins,
                    plugin_key,
                    lambda plugin: matches_filters(
                        plugin,
                        supports=set(),
                        catalog_yaml=set(),
                        membership=set(),
                        names=args.name,
                        lifecycles=[],
                    ),
                )
            report = diff_items(from_plugins, to_plugins, plugin_key)
            warnings = list(report.warnings)
            note_missing_core(core_from, ref_from, warnings)
            note_missing_core(core_to, ref_to, warnings)
            warnings.extend(_prefix_notes(version_from, notes_from))
            warnings.extend(_prefix_notes(version_to, notes_to))
            warnings.extend(_prefix_notes(version_from, build_warnings(from_plugins, scanned_from)))
            warnings.extend(_prefix_notes(version_to, build_warnings(to_plugins, scanned_to)))
            payload = _diff_payload(
                version_from=version_from,
                ref_from=ref_from,
                version_to=version_to,
                ref_to=ref_to,
                source=source,
                report=report,
                warnings=warnings,
                filtered=identity,
                scanned_from=scanned_from,
                scanned_to=scanned_to,
            )
            _emit(
                payload,
                render_diff_markdown(
                    version_from=version_from,
                    ref_from=ref_from,
                    version_to=version_to,
                    ref_to=ref_to,
                    source=source,
                    report=report,
                    warnings=warnings,
                    filtered=identity,
                    scanned_from=scanned_from,
                    scanned_to=scanned_to,
                ),
                args.json,
            )
            if scanned_from == 0 and scanned_to == 0:
                return EMPTY_EXIT
            return 0

        try:
            plugins, ref, source, temp_dir = collect_overlay(
                version=args.version,
                repo_arg=args.repo,
                ref_arg=args.ref,
                workdir=args.workdir,
                temp_prefix="rhdh-product-catalog-plugins-",
                load_workdir=load_from_workdir,
                load_git=load_from_git,
            )
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return RESOLVE_EXIT
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or str(exc)).strip()
            print(err, file=sys.stderr)
            return RESOLVE_EXIT

        scanned = len(plugins)
        core_index = apply_plugin_core(
            plugins,
            source=source,
            repo_arg=args.repo,
            ref=ref,
            workdir=args.workdir,
        )
        filtered = bool(
            support_filters
            or catalog_yaml
            or membership
            or args.name
            or args.lifecycle
            or args.core
            or args.enabled_ootb
            or args.disabled_ootb
        )
        plugins = [
            p
            for p in plugins
            if matches_filters(
                p,
                supports=support_filters,
                catalog_yaml=catalog_yaml,
                membership=membership,
                names=args.name,
                lifecycles=args.lifecycle,
                core_only=args.core,
                ootb_enabled=args.enabled_ootb,
                ootb_disabled=args.disabled_ootb,
            )
        ]
        plugins = sort_plugins(plugins)
        warnings = list(_load_notes) + build_warnings(plugins, scanned)
        note_missing_core(core_index, ref, warnings)

        payload = {
            "version": args.version,
            "ref": ref,
            "source": source,
            "scanned": scanned,
            "filtered": filtered,
            "counts": {k: sum(1 for p in plugins if p["support"] == k) for k in SUPPORT_ORDER},
            "catalog_membership": {
                IN_CATALOG: sum(1 for p in plugins if p.get("catalog_membership") == IN_CATALOG),
                PACKAGED: sum(1 for p in plugins if p.get("catalog_membership") == PACKAGED),
            },
            "catalog_yaml": {
                "pre-installed": sum(1 for p in plugins if p["catalog_yaml"] == "pre-installed"),
                "custom": sum(1 for p in plugins if p["catalog_yaml"] == "custom"),
            },
            "core": {
                "enabled": sum(1 for p in plugins if p.get("core_ootb") == "enabled"),
                "disabled": sum(1 for p in plugins if p.get("core_ootb") == "disabled"),
                "mixed": sum(1 for p in plugins if p.get("core_ootb") == "mixed"),
                "not_core": sum(1 for p in plugins if not p.get("core")),
            },
            "total": len(plugins),
            "warnings": warnings,
            "plugins": plugins,
        }
        _emit(
            payload,
            render_markdown(
                version=args.version,
                ref=ref,
                source=source,
                plugins=plugins,
                warnings=warnings,
                filtered=filtered,
                scanned=scanned,
                core_index=core_index,
            ),
            args.json,
        )
        if scanned == 0:
            return EMPTY_EXIT
        return 0
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    sys.exit(main())
