#!/usr/bin/env python3
"""List RHDH overlay Package metadata for a release.

Reads workspaces/<name>/metadata/*.yaml from rhdh-plugin-export-overlays.
Does not check out or otherwise mutate a local working tree.
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

from default_packages import (  # noqa: E402
    DEFAULT_PACKAGES_REL,
    DEFAULT_PACKAGES_URL,
    CoreIndex,
    enrich_packages_with_core,
    plugin_package_refs,
)
from overlay_repo import (  # noqa: E402
    collect_overlay,
    collect_overlay_pair,
    ensure_git_ref,
    list_via_git,
    load_core_index,
    read_files_via_git,
    read_via_git,
    version_to_ref,
)
from package_txt_compare import (  # noqa: E402
    COMMUNITY_TXT,
    SUPPORTED_TXT,
    compare_packages_to_txt,
    compare_payload,
    load_txt_files_from_root,
    render_compare_markdown,
)
from diff import (  # noqa: E402
    DiffReport,
    arrow,
    diff_items,
    package_key,
    restrict_to_matching_identities,
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
from yaml_lite import parse_yaml  # noqa: E402

METADATA_PATH = re.compile(r"^workspaces/([^/]+)/metadata/[^/]+\.ya?ml$")
USAGE_EXIT = 2
RESOLVE_EXIT = 3
EMPTY_EXIT = 1


def source_url(doc: dict[str, Any]) -> str:
    meta = doc.get("metadata") or {}
    links = meta.get("links") or []
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            title = as_str(link.get("title")).lower()
            if title == "source code":
                return as_str(link.get("url"))
    annotations = meta.get("annotations") or {}
    if isinstance(annotations, dict):
        loc = annotations.get("backstage.io/source-location")
        loc_s = as_str(loc)
        if loc_s.startswith("url:"):
            return loc_s[4:]
        return loc_s
    return ""


def trim_package_yaml(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if re.match(r"^  appConfigExamples:\s*(#.*)?$", line):
            break
        lines.append(line)
    return "\n".join(lines)


def extract_package(doc: dict[str, Any], rel_path: str, workspace: str) -> dict[str, Any]:
    meta = doc.get("metadata") or {}
    spec = doc.get("spec") or {}
    backstage = spec.get("backstage") or {}
    if not isinstance(backstage, dict):
        backstage = {}
    support_key = normalize_support(spec.get("support"))
    title = (
        as_str(meta.get("title"))
        or as_str(meta.get("name"))
        or as_str(spec.get("packageName"))
    )
    return {
        "workspace": workspace,
        "file": rel_path,
        "kind": as_str(doc.get("kind")),
        "name": as_str(meta.get("name")),
        "title": title,
        "support": support_key,
        "support_label": SUPPORT_LABELS[support_key],
        "package_name": as_str(spec.get("packageName")),
        "source": source_url(doc),
        "backstage": as_str(backstage.get("supportedVersions")),
        "role": as_str(backstage.get("role")),
        "version": as_str(spec.get("version")),
        "author": as_str(spec.get("author")),
        "lifecycle": as_str(spec.get("lifecycle")),
        "support_raw": spec.get("support"),
    }


def is_metadata_path(rel_path: str) -> bool:
    rel = rel_path.replace("\\", "/")
    if "scripts/tests/" in rel:
        return False
    return bool(METADATA_PATH.match(rel))


def workspace_of(rel_path: str) -> str:
    m = METADATA_PATH.match(rel_path.replace("\\", "/"))
    if not m:
        raise ValueError(rel_path)
    return m.group(1)


def list_metadata_on_disk(root: Path) -> list[Path]:
    workspaces = root / "workspaces"
    if not workspaces.is_dir():
        return []
    files: list[Path] = []
    for meta_dir in sorted(workspaces.glob("*/metadata")):
        if "scripts/tests" in meta_dir.as_posix():
            continue
        for path in sorted(meta_dir.iterdir()):
            if path.suffix in {".yaml", ".yml"} and path.is_file():
                files.append(path)
    return files


def load_packages_from_text(rel_path: str, text: str) -> dict[str, Any] | None:
    if not is_metadata_path(rel_path):
        return None
    workspace = workspace_of(rel_path)
    try:
        doc = parse_yaml(trim_package_yaml(text))
    except Exception as exc:
        return {
            "workspace": workspace,
            "file": rel_path,
            "kind": "",
            "title": rel_path,
            "support": "unknown",
            "support_label": SUPPORT_LABELS["unknown"],
            "package_name": "",
            "source": "",
            "backstage": "",
            "role": "",
            "version": "",
            "author": "",
            "lifecycle": "",
            "parse_error": str(exc),
        }
    if as_str(doc.get("kind")) != "Package":
        return None
    return extract_package(doc, rel_path, workspace)


def load_from_workdir(root: Path) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for path in list_metadata_on_disk(root):
        rel = path.relative_to(root).as_posix()
        pkg = load_packages_from_text(rel, path.read_text(encoding="utf-8"))
        if pkg:
            packages.append(pkg)
    return packages


def load_from_git(repo: Path, ref: str) -> tuple[list[dict[str, Any]], str]:
    resolved = ensure_git_ref(repo, ref)
    rels = [rel for rel in list_via_git(repo, resolved, "workspaces") if is_metadata_path(rel)]
    texts = read_files_via_git(repo, resolved, rels)
    packages: list[dict[str, Any]] = []
    for rel in rels:
        text = texts.get(rel)
        if text is None:
            continue
        pkg = load_packages_from_text(rel, text)
        if pkg:
            packages.append(pkg)
    return packages, resolved


def matches_filters(
    pkg: dict[str, Any],
    supports: set[str],
    workspaces: list[str],
    packages: list[str],
    *,
    core_only: bool = False,
    ootb_enabled: bool = False,
    ootb_disabled: bool = False,
) -> bool:
    if supports and pkg["support"] not in supports:
        return False
    if core_only and not pkg.get("core"):
        return False
    if ootb_enabled and pkg.get("core_ootb") != "enabled":
        return False
    if ootb_disabled and pkg.get("core_ootb") != "disabled":
        return False
    if workspaces:
        ws = pkg["workspace"].lower()
        if not any(w.lower() in ws or ws in w.lower() for w in workspaces):
            return False
    if packages:
        hay = " ".join(
            [
                pkg.get("package_name", ""),
                pkg.get("title", ""),
                pkg.get("name", ""),
                pkg.get("file", ""),
            ]
        ).lower()
        if not any(p.lower() in hay for p in packages):
            return False
    return True


def sort_packages(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rank = {key: i for i, key in enumerate(SUPPORT_ORDER)}

    def key(pkg: dict[str, Any]) -> tuple:
        return (
            pkg["workspace"].lower(),
            rank.get(pkg["support"], len(SUPPORT_ORDER)),
            pkg["title"].lower(),
            pkg.get("package_name", "").lower(),
        )

    return sorted(packages, key=key)


def group_by_workspace(packages: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for pkg in packages:
        ws = pkg["workspace"]
        if ws not in grouped:
            grouped[ws] = []
            order.append(ws)
        grouped[ws].append(pkg)
    return [(ws, grouped[ws]) for ws in order]


def source_cell(url: str) -> str:
    if not url:
        return "—"
    return f"[source]({url})"


def core_cell(pkg: dict[str, Any]) -> str:
    if not pkg.get("core"):
        return "—"
    return md_cell(pkg.get("core_ootb_label") or pkg.get("core_ootb", ""))


def render_markdown(
    *,
    version: str,
    ref: str,
    source: dict[str, str],
    packages: list[dict[str, Any]],
    warnings: list[str],
    filtered: bool,
    scanned: int,
    core_index: CoreIndex | None = None,
) -> str:
    counts = Counter(pkg["support"] for pkg in packages)
    workspaces = group_by_workspace(packages)
    lines: list[str] = [
        f"# RHDH {version} packages (`{ref}`)",
        "",
        f"**{len(packages)} package{'s' if len(packages) != 1 else ''}** "
        f"in **{len(workspaces)} workspace{'s' if len(workspaces) != 1 else ''}**"
        + (" (filtered)" if filtered else ""),
        "",
        f"_Source: {source_caption(source, ref)}_",
        "",
        "| Support level | Count |",
        "|---|---|",
    ]
    for key in SUPPORT_ORDER:
        count = counts.get(key, 0)
        if key == "unknown" and count == 0:
            continue
        lines.append(f"| {SUPPORT_LABELS[key]} | {count} |")
    if core_index:
        core_counts = Counter(
            p.get("core_ootb") for p in packages if p.get("core")
        )
        lines.extend(
            [
                "",
                f"| Core ([default.packages.yaml]({DEFAULT_PACKAGES_URL})) | Count |",
                "|---|---|",
                f"| enabled OOTB | {core_counts.get('enabled', 0)} |",
                f"| disabled OOTB | {core_counts.get('disabled', 0)} |",
                f"| not core | {sum(1 for p in packages if not p.get('core'))} |",
            ]
        )
    lines.extend(["", f"Scanned {scanned} Package YAML files on `{ref}`."])
    if warnings:
        lines.append("")
        for warning in warnings:
            lines.append(f"> {warning}")
    for workspace, pkgs in workspaces:
        lines.extend(
            [
                "",
                f"## {workspace}",
                "",
                "| Title | Support | Package | Source | Backstage | Role | Version | Author | Lifecycle | Core OOTB |",
                "|---|---|---|---|---|---|---|---|---|---|",
            ]
        )
        for pkg in pkgs:
            lines.append(
                "| "
                + " | ".join(
                    [
                        md_cell(pkg["title"]),
                        md_cell(pkg["support_label"]),
                        md_cell(pkg["package_name"]),
                        source_cell(pkg["source"]),
                        md_cell(pkg["backstage"]),
                        md_cell(pkg["role"]),
                        md_cell(pkg["version"]),
                        md_cell(pkg["author"]),
                        md_cell(pkg["lifecycle"]),
                        core_cell(pkg),
                    ]
                )
                + " |"
            )
    lines.append("")
    return "\n".join(lines)


def _package_row_cells(pkg: dict[str, Any]) -> list[str]:
    return [
        md_cell(pkg["title"]),
        md_cell(pkg["support_label"]),
        md_cell(pkg["package_name"]),
        source_cell(pkg["source"]),
        md_cell(pkg["backstage"]),
        md_cell(pkg["role"]),
        md_cell(pkg["version"]),
        md_cell(pkg["author"]),
        md_cell(pkg["lifecycle"]),
        core_cell(pkg),
        md_cell(pkg["workspace"]),
    ]


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


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
    noun = "package"
    lines: list[str] = [
        f"# RHDH package diff: {version_from} → {version_to} "
        f"(`{ref_from}` → `{ref_to}`)",
        "",
        f"_Source: {source_caption_diff(source, ref_from, ref_to)}_",
        "",
        f"Scanned {scanned_from} Package YAML files on `{ref_from}` and "
        f"{scanned_to} on `{ref_to}`"
        + (" (filtered)" if filtered else "")
        + ".",
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

    snapshot_headers = [
        "Title",
        "Support",
        "Package",
        "Source",
        "Backstage",
        "Role",
        "Version",
        "Author",
        "Lifecycle",
        "Workspace",
    ]

    def section(title: str, body: list[str]) -> None:
        lines.extend(["", f"## {title}", ""])
        lines.extend(body)

    if support_rows:
        section(
            "Support level changed",
            _md_table(
                ["Title", "Workspace", "Package", "Support"],
                [
                    [
                        md_cell(row["to"]["title"]),
                        md_cell(row["to"]["workspace"]),
                        md_cell(row["to"]["package_name"]),
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
                snapshot_headers,
                [_package_row_cells(pkg) for pkg in report.added],
            ),
        )
    if lifecycle_rows:
        section(
            "Lifecycle changed",
            _md_table(
                ["Title", "Workspace", "Package", "Lifecycle"],
                [
                    [
                        md_cell(row["to"]["title"]),
                        md_cell(row["to"]["workspace"]),
                        md_cell(row["to"]["package_name"]),
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
                snapshot_headers,
                [_package_row_cells(pkg) for pkg in report.removed],
            ),
        )
    if not (support_rows or report.added or lifecycle_rows or report.removed):
        lines.extend(
            [
                "",
                f"No support, lifecycle, added, or removed {noun} changes "
                f"between {version_from} and {version_to}.",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def build_warnings(packages: list[dict[str, Any]], scanned: int) -> list[str]:
    warnings: list[str] = []
    unknown = [p for p in packages if p["support"] == "unknown"]
    if unknown:
        warnings.append(
            f"{len(unknown)} package(s) have missing or unrecognized spec.support "
            "(listed as Unknown, last within each workspace)."
        )
    parse_errors = [p for p in packages if p.get("parse_error")]
    if parse_errors:
        warnings.append(f"{len(parse_errors)} metadata file(s) failed to parse.")
    missing_source = [p for p in packages if not p.get("source")]
    if missing_source:
        warnings.append(f"{len(missing_source)} package(s) have no Source Code link.")
    if scanned and not packages:
        warnings.append("No Package entities found in workspaces/*/metadata.")
    return warnings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "List RHDH packages from rhdh-plugin-export-overlays Package metadata, "
            "grouped by workspace then decreasing support level. "
            "Use --diff FROM TO to compare two versions. "
            "Use --compare-txt to check metadata against rhdh-*-packages.txt."
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
        "--workspace",
        action="append",
        default=[],
        help="Filter by workspace name substring (repeatable)",
    )
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        help="Filter by package name/title substring (repeatable)",
    )
    parser.add_argument(
        "--core",
        action="store_true",
        help="Only packages listed in default.packages.yaml (core RHDH experience)",
    )
    parser.add_argument(
        "--enabled-ootb",
        action="store_true",
        help="Only core packages enabled out of the box in default.packages.yaml",
    )
    parser.add_argument(
        "--disabled-ootb",
        action="store_true",
        help="Only core packages disabled out of the box in default.packages.yaml",
    )
    parser.add_argument(
        "--compare-txt",
        action="store_true",
        help=(
            "Compare Package metadata support levels to rhdh-community-packages.txt "
            "and rhdh-supported-packages.txt on the overlay ref"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of markdown")
    return parser.parse_args(argv)


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


def repo_for_core(source: dict[str, str], repo_arg: str | None) -> Path | None:
    stype = source.get("type")
    if stype in ("local-git", "clone"):
        return Path(source["path"])
    if repo_arg:
        repo = Path(repo_arg).expanduser().resolve()
        if (repo / ".git").is_dir():
            return repo
    return None


def load_package_txt_lists(
    source: dict[str, str],
    repo: Path | None,
    ref: str,
) -> tuple[str | None, str | None]:
    root = Path(source.get("path", ""))
    if root.is_dir():
        comm, supp = load_txt_files_from_root(root)
        if comm is not None or supp is not None:
            return comm, supp
    if repo and (repo / ".git").is_dir():
        resolved = ensure_git_ref(repo, ref)
        comm: str | None = None
        supp: str | None = None
        try:
            comm = read_via_git(repo, resolved, COMMUNITY_TXT)
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
        try:
            supp = read_via_git(repo, resolved, SUPPORTED_TXT)
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
        return comm, supp
    return None, None


def build_txt_compare_warnings(
    community_text: str | None,
    supported_text: str | None,
    ref: str,
) -> list[str]:
    warnings: list[str] = []
    if community_text is None:
        warnings.append(f"`{COMMUNITY_TXT}` not found on `{ref}`.")
    if supported_text is None:
        warnings.append(f"`{SUPPORTED_TXT}` not found on `{ref}`.")
    return warnings


def note_missing_core(core_index: CoreIndex | None, ref: str, warnings: list[str]) -> None:
    if core_index is None:
        warnings.append(
            f"`{DEFAULT_PACKAGES_REL}` not found on `{ref}`; Core OOTB column is blank. "
            f"See {DEFAULT_PACKAGES_URL}"
        )


def validate_args(args: argparse.Namespace) -> str | None:
    if args.diff and args.compare_txt:
        return "--compare-txt cannot be used with --diff."
    if args.compare_txt:
        if not args.version:
            return "A version is required with --compare-txt."
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

    temp_dir = None
    try:
        if args.compare_txt:
            if support_filters or args.workspace or args.package or args.core or args.enabled_ootb or args.disabled_ootb:
                print(
                    "note: list filters are ignored with --compare-txt.",
                    file=sys.stderr,
                )
            try:
                packages, ref, source, temp_dir = collect_overlay(
                    version=args.version,
                    repo_arg=args.repo,
                    ref_arg=args.ref,
                    workdir=args.workdir,
                    temp_prefix="rhdh-product-catalog-packages-",
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

            community_text, supported_text = load_package_txt_lists(
                source, repo_for_core(source, args.repo), ref
            )
            warnings = build_txt_compare_warnings(community_text, supported_text, ref)
            report = compare_packages_to_txt(
                packages,
                community_text=community_text,
                supported_text=supported_text,
            )
            payload = compare_payload(
                version=args.version,
                ref=ref,
                source=source,
                report=report,
                warnings=warnings,
            )
            _emit(
                payload,
                render_compare_markdown(
                    version=args.version,
                    ref=ref,
                    source_caption=source_caption(source, ref),
                    report=report,
                    warnings=warnings,
                ),
                args.json,
            )
            if community_text is None and supported_text is None:
                return RESOLVE_EXIT
            if len(packages) == 0:
                return EMPTY_EXIT
            return 0

        if args.diff:
            version_from, version_to = args.diff
            if support_filters:
                print(
                    "note: --support is ignored with --diff "
                    "(support level is one of the compared fields).",
                    file=sys.stderr,
                )
            try:
                from_pkgs, ref_from, to_pkgs, ref_to, source, temp_dir = collect_overlay_pair(
                    version_from=version_from,
                    version_to=version_to,
                    repo_arg=args.repo,
                    temp_prefix="rhdh-product-catalog-packages-",
                    load_git=load_from_git,
                    load_workdir=load_from_workdir,
                )
            except FileNotFoundError as exc:
                print(str(exc), file=sys.stderr)
                return RESOLVE_EXIT
            except subprocess.CalledProcessError as exc:
                err = (exc.stderr or exc.stdout or str(exc)).strip()
                print(err, file=sys.stderr)
                return RESOLVE_EXIT

            scanned_from = len(from_pkgs)
            scanned_to = len(to_pkgs)
            ref_from = version_to_ref(version_from)
            ref_to = version_to_ref(version_to)
            core_from = load_core_index(repo_for_core(source, args.repo), ref_from, source)
            core_to = load_core_index(repo_for_core(source, args.repo), ref_to, source)
            enrich_packages_with_core(from_pkgs, core_from)
            enrich_packages_with_core(to_pkgs, core_to)
            identity = bool(args.workspace or args.package)
            if identity:
                from_pkgs, to_pkgs = restrict_to_matching_identities(
                    from_pkgs,
                    to_pkgs,
                    package_key,
                    lambda pkg: matches_filters(pkg, set(), args.workspace, args.package),
                )
            report = diff_items(from_pkgs, to_pkgs, package_key)
            warnings = list(report.warnings)
            note_missing_core(core_from, ref_from, warnings)
            note_missing_core(core_to, ref_to, warnings)
            warnings.extend(build_warnings(from_pkgs, scanned_from))
            warnings.extend(build_warnings(to_pkgs, scanned_to))
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
            packages, ref, source, temp_dir = collect_overlay(
                version=args.version,
                repo_arg=args.repo,
                ref_arg=args.ref,
                workdir=args.workdir,
                temp_prefix="rhdh-product-catalog-packages-",
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

        scanned = len(packages)
        core_index = load_core_index(repo_for_core(source, args.repo), ref, source)
        enrich_packages_with_core(packages, core_index)
        filtered = bool(
            support_filters
            or args.workspace
            or args.package
            or args.core
            or args.enabled_ootb
            or args.disabled_ootb
        )
        packages = [
            pkg
            for pkg in packages
            if matches_filters(
                pkg,
                support_filters,
                args.workspace,
                args.package,
                core_only=args.core,
                ootb_enabled=args.enabled_ootb,
                ootb_disabled=args.disabled_ootb,
            )
        ]
        packages = sort_packages(packages)
        warnings = build_warnings(packages, scanned)
        note_missing_core(core_index, ref, warnings)

        payload = {
            "version": args.version,
            "ref": ref,
            "source": source,
            "scanned": scanned,
            "filtered": filtered,
            "counts": {k: sum(1 for p in packages if p["support"] == k) for k in SUPPORT_ORDER},
            "core": {
                "enabled": sum(1 for p in packages if p.get("core_ootb") == "enabled"),
                "disabled": sum(1 for p in packages if p.get("core_ootb") == "disabled"),
                "not_core": sum(1 for p in packages if not p.get("core")),
            },
            "total": len(packages),
            "warnings": warnings,
            "workspaces": [
                {"name": ws, "packages": pkgs} for ws, pkgs in group_by_workspace(packages)
            ],
        }
        _emit(
            payload,
            render_markdown(
                version=args.version,
                ref=ref,
                source=source,
                packages=packages,
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
