"""Compare Package metadata support levels to rhdh-*-packages.txt export lists."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from support import as_str, md_cell

COMMUNITY_TXT = "rhdh-community-packages.txt"
SUPPORTED_TXT = "rhdh-supported-packages.txt"
COMMUNITY_TXT_URL = (
    "https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/" + COMMUNITY_TXT
)
SUPPORTED_TXT_URL = (
    "https://github.com/redhat-developer/rhdh-plugin-export-overlays/blob/main/" + SUPPORTED_TXT
)

COMMUNITY_SUPPORT = frozenset({"community", "dev-preview"})
SUPPORTED_SUPPORT = frozenset({"generally-available", "tech-preview"})


def parse_txt_paths(text: str) -> set[str]:
    paths: set[str] = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            paths.add(line.replace("\\", "/").strip("/"))
    return paths


def _norm_token(value: str) -> str:
    return value.replace("-", "").replace("_", "").lower()


def _leaf_matches_package(leaf: str, meta: str, stem: str, npm: str) -> bool:
    if meta == leaf or stem == leaf:
        return True
    if meta == f"{leaf}-backend" or stem == f"{leaf}-backend":
        return True
    if leaf.endswith("-backend") and (meta == leaf or stem == leaf):
        return True
    if not leaf.endswith("-backend") and (meta.endswith("-backend") or stem.endswith("-backend")):
        return False
    if leaf.replace("-backend", "") == meta.replace("-backend", ""):
        return True
    if _norm_token(leaf) in _norm_token(meta) and not (
        not leaf.endswith("-backend") and meta.endswith("-backend")
    ):
        return True
    if _norm_token(leaf) in _norm_token(npm) and not npm.endswith("-backend"):
        return True
    return False


def packages_for_txt_path(
    path: str, by_workspace: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Map a txt workspace path to Package metadata rows."""
    ws, *rest = path.split("/")
    leaf = Path(path).name
    hits: list[dict[str, Any]] = []

    def consider(pkg: dict[str, Any]) -> None:
        if pkg not in hits:
            hits.append(pkg)

    for pkg in by_workspace.get(ws, []):
        meta = as_str(pkg.get("name"))
        stem = Path(as_str(pkg.get("file"))).stem
        npm = as_str(pkg.get("package_name"))
        if _leaf_matches_package(leaf, meta, stem, npm):
            consider(pkg)
        elif path.endswith(f"/{meta}") or path.endswith(f"/{stem}"):
            consider(pkg)

    if not hits and len(rest) >= 2:
        module = rest[-1]
        token = module.replace("-actions", "")
        for pkg in by_workspace.get(ws, []):
            meta = as_str(pkg.get("name"))
            npm = as_str(pkg.get("package_name"))
            if (
                module in meta
                or module in Path(as_str(pkg.get("file"))).stem
                or token in npm
                or _norm_token(token) in _norm_token(npm)
            ):
                consider(pkg)

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for pkg in hits:
        npm = as_str(pkg.get("package_name"))
        if npm and npm not in seen:
            seen.add(npm)
            out.append(pkg)
    return out


def index_by_workspace(packages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_ws: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pkg in packages:
        by_ws[as_str(pkg.get("workspace"))].append(pkg)
    return by_ws


@dataclass
class TxtCompareReport:
    community_paths: set[str] = field(default_factory=set)
    supported_paths: set[str] = field(default_factory=set)
    path_overlap: list[str] = field(default_factory=list)
    txt_community_mismatches: list[dict[str, Any]] = field(default_factory=list)
    txt_supported_mismatches: list[dict[str, Any]] = field(default_factory=list)
    txt_unmapped_paths: list[str] = field(default_factory=list)
    metadata_missing_from_community: list[dict[str, Any]] = field(default_factory=list)
    metadata_missing_from_supported: list[dict[str, Any]] = field(default_factory=list)
    wrong_list: list[dict[str, Any]] = field(default_factory=list)
    mapped_package_count: int = 0
    total_packages: int = 0
    missing_community_txt: bool = False
    missing_supported_txt: bool = False

    def aligned(self) -> bool:
        return (
            not self.txt_community_mismatches
            and not self.txt_supported_mismatches
            and not self.wrong_list
            and not self.missing_community_txt
            and not self.missing_supported_txt
        )


def compare_packages_to_txt(
    packages: list[dict[str, Any]],
    *,
    community_text: str | None,
    supported_text: str | None,
) -> TxtCompareReport:
    report = TxtCompareReport(total_packages=len(packages))
    report.missing_community_txt = community_text is None
    report.missing_supported_txt = supported_text is None
    if community_text is None and supported_text is None:
        return report

    community_paths = parse_txt_paths(community_text or "")
    supported_paths = parse_txt_paths(supported_text or "")
    report.community_paths = community_paths
    report.supported_paths = supported_paths
    report.path_overlap = sorted(community_paths & supported_paths)

    by_ws = index_by_workspace(packages)
    path_pkgs: dict[str, list[dict[str, Any]]] = {}
    for path in community_paths | supported_paths:
        path_pkgs[path] = packages_for_txt_path(path, by_ws)

    pkg_lists: dict[str, set[str]] = defaultdict(set)
    for path, pkgs in path_pkgs.items():
        which = "community" if path in community_paths else "supported"
        for pkg in pkgs:
            npm = as_str(pkg.get("package_name"))
            if npm:
                pkg_lists[npm].add(which)

    report.mapped_package_count = len(pkg_lists)

    for path in sorted(community_paths):
        pkgs = path_pkgs.get(path, [])
        if not pkgs:
            report.txt_unmapped_paths.append(path)
            continue
        for pkg in pkgs:
            if pkg["support"] not in COMMUNITY_SUPPORT:
                report.txt_community_mismatches.append(_row(path, pkg, "community"))

    for path in sorted(supported_paths):
        pkgs = path_pkgs.get(path, [])
        if not pkgs:
            if path not in report.txt_unmapped_paths:
                report.txt_unmapped_paths.append(path)
            continue
        for pkg in pkgs:
            if pkg["support"] not in SUPPORTED_SUPPORT:
                report.txt_supported_mismatches.append(_row(path, pkg, "supported"))

    for pkg in packages:
        npm = as_str(pkg.get("package_name"))
        if not npm:
            continue
        lists = pkg_lists.get(npm, set())
        support = pkg["support"]
        if support in COMMUNITY_SUPPORT:
            if "community" not in lists:
                report.metadata_missing_from_community.append(_meta_row(pkg))
            if "supported" in lists:
                report.wrong_list.append(_wrong_row(pkg, "community/dev-preview", "supported"))
        elif support in SUPPORTED_SUPPORT:
            if "supported" not in lists:
                report.metadata_missing_from_supported.append(_meta_row(pkg))
            if "community" in lists:
                report.wrong_list.append(_wrong_row(pkg, "ga/tech-preview", "community"))

    report.txt_unmapped_paths = sorted(set(report.txt_unmapped_paths))
    return report


def _row(path: str, pkg: dict[str, Any], list_name: str) -> dict[str, Any]:
    return {
        "txt_path": path,
        "list": list_name,
        "package_name": as_str(pkg.get("package_name")),
        "title": as_str(pkg.get("title")),
        "support": pkg["support"],
        "support_label": pkg.get("support_label", ""),
        "workspace": as_str(pkg.get("workspace")),
    }


def _meta_row(pkg: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_name": as_str(pkg.get("package_name")),
        "title": as_str(pkg.get("title")),
        "support": pkg["support"],
        "support_label": pkg.get("support_label", ""),
        "workspace": as_str(pkg.get("workspace")),
    }


def _wrong_row(pkg: dict[str, Any], expected: str, actual_list: str) -> dict[str, Any]:
    row = _meta_row(pkg)
    row["expected_list"] = expected
    row["actual_list"] = actual_list
    return row


def load_txt_files_from_root(root: Path) -> tuple[str | None, str | None]:
    comm = root / COMMUNITY_TXT
    supp = root / SUPPORTED_TXT
    return (
        comm.read_text(encoding="utf-8") if comm.is_file() else None,
        supp.read_text(encoding="utf-8") if supp.is_file() else None,
    )


def render_compare_markdown(
    *,
    version: str,
    ref: str,
    source_caption: str,
    report: TxtCompareReport,
    warnings: list[str],
) -> str:
    lines = [
        f"# RHDH {version} packages vs export txt lists (`{ref}`)",
        "",
        f"**{report.total_packages}** Package metadata rows compared to "
        f"[{COMMUNITY_TXT}]({COMMUNITY_TXT_URL}) and "
        f"[{SUPPORTED_TXT}]({SUPPORTED_TXT_URL}).",
        "",
        f"_Source: {source_caption}_",
        "",
        "Txt lines are workspace paths (`<workspace>/plugins/<folder>`). They are "
        "**export/build manifests**, not a full catalog inventory.",
        "",
        "| | Count |",
        "|---|---|",
        f"| Community txt paths | {len(report.community_paths)} |",
        f"| Supported txt paths | {len(report.supported_paths)} |",
        f"| Paths in both txt files | {len(report.path_overlap)} |",
        f"| Packages mapped from txt paths | {report.mapped_package_count} |",
        f"| Txt → metadata support mismatches | "
        f"{len(report.txt_community_mismatches) + len(report.txt_supported_mismatches)} |",
        f"| Metadata on wrong txt list for support | {len(report.wrong_list)} |",
        f"| Txt paths with no Package metadata | {len(report.txt_unmapped_paths)} |",
        f"| Community/DP metadata not in community txt | "
        f"{len(report.metadata_missing_from_community)} |",
        f"| GA/TP metadata not in supported txt | {len(report.metadata_missing_from_supported)} |",
        "",
    ]

    if report.aligned():
        lines.append(
            "All mapped txt paths agree with Package metadata support levels "
            "(community txt → Community/Developer Preview; supported txt → GA/Tech Preview)."
        )
        lines.append("")
    else:
        lines.append("**Alignment issues found** (see sections below).")
        lines.append("")

    if warnings:
        for note in warnings:
            lines.append(f"> {note}")
        lines.append("")

    _section_table(
        lines,
        "## Community txt → metadata mismatches",
        "Expected Community or Developer Preview.",
        report.txt_community_mismatches,
        ["Txt path", "Package", "Support", "Workspace"],
        lambda r: [
            md_cell(r["txt_path"]),
            md_cell(r["package_name"]),
            md_cell(r["support_label"]),
            md_cell(r["workspace"]),
        ],
    )
    _section_table(
        lines,
        "## Supported txt → metadata mismatches",
        "Expected Generally Available or Tech Preview.",
        report.txt_supported_mismatches,
        ["Txt path", "Package", "Support", "Workspace"],
        lambda r: [
            md_cell(r["txt_path"]),
            md_cell(r["package_name"]),
            md_cell(r["support_label"]),
            md_cell(r["workspace"]),
        ],
    )
    _section_table(
        lines,
        "## Metadata on wrong txt list",
        "Support level and txt list disagree.",
        report.wrong_list,
        ["Package", "Support", "Expected list", "Listed in"],
        lambda r: [
            md_cell(r["package_name"]),
            md_cell(r["support_label"]),
            md_cell(r["expected_list"]),
            md_cell(r["actual_list"]),
        ],
    )
    _section_table(
        lines,
        "## Txt paths with no Package metadata",
        "Path appears in a txt file but no matching `workspaces/*/metadata` row was found.",
        [{"path": p} for p in report.txt_unmapped_paths],
        ["Txt path"],
        lambda r: [md_cell(r["path"])],
    )
    _section_table(
        lines,
        "## Community / Developer Preview not in community txt",
        "In overlay metadata but not listed under community txt (often optional catalog content).",
        report.metadata_missing_from_community,
        ["Package", "Support", "Workspace"],
        lambda r: [
            md_cell(r["package_name"]),
            md_cell(r["support_label"]),
            md_cell(r["workspace"]),
        ],
    )
    _section_table(
        lines,
        "## GA / Tech Preview not in supported txt",
        "In overlay metadata but not listed under supported txt.",
        report.metadata_missing_from_supported,
        ["Package", "Support", "Workspace"],
        lambda r: [
            md_cell(r["package_name"]),
            md_cell(r["support_label"]),
            md_cell(r["workspace"]),
        ],
    )

    return "\n".join(lines).rstrip() + "\n"


def _section_table(
    lines: list[str],
    heading: str,
    blurb: str,
    rows: list[dict[str, Any]],
    headers: list[str],
    cells: Any,
) -> None:
    lines.extend([heading, "", blurb, ""])
    if not rows:
        lines.append("_None._")
        lines.append("")
        return
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        line = "| " + " | ".join(cells(row)) + " |"
        lines.append(line)
    lines.append("")


def compare_payload(
    *,
    version: str,
    ref: str,
    source: dict[str, str],
    report: TxtCompareReport,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "mode": "compare-txt",
        "version": version,
        "ref": ref,
        "source": source,
        "aligned": report.aligned(),
        "counts": {
            "packages": report.total_packages,
            "community_paths": len(report.community_paths),
            "supported_paths": len(report.supported_paths),
            "path_overlap": len(report.path_overlap),
            "mapped_packages": report.mapped_package_count,
            "txt_community_mismatches": len(report.txt_community_mismatches),
            "txt_supported_mismatches": len(report.txt_supported_mismatches),
            "wrong_list": len(report.wrong_list),
            "txt_unmapped_paths": len(report.txt_unmapped_paths),
            "metadata_missing_from_community": len(report.metadata_missing_from_community),
            "metadata_missing_from_supported": len(report.metadata_missing_from_supported),
        },
        "warnings": warnings,
        "path_overlap": report.path_overlap,
        "txt_community_mismatches": report.txt_community_mismatches,
        "txt_supported_mismatches": report.txt_supported_mismatches,
        "wrong_list": report.wrong_list,
        "txt_unmapped_paths": report.txt_unmapped_paths,
        "metadata_missing_from_community": report.metadata_missing_from_community,
        "metadata_missing_from_supported": report.metadata_missing_from_supported,
        "missing_community_txt": report.missing_community_txt,
        "missing_supported_txt": report.missing_supported_txt,
    }
