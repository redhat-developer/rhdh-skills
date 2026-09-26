"""Flag support-level mismatches between Plugin catalog entities and Package metadata."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from default_packages import (
    build_metadata_name_index,
    resolve_plugin_npm_packages,
)
from support import SUPPORT_ORDER, as_str, md_cell


def support_rank(support: str) -> int:
    try:
        return SUPPORT_ORDER.index(support)
    except ValueError:
        return len(SUPPORT_ORDER)


def link_plugins_to_packages(
    plugins: list[dict[str, Any]],
    packages: list[dict[str, Any]],
) -> None:
    """Attach linked Package rows to each plugin (`linked_packages` + `npm_packages`)."""
    metadata_index = build_metadata_name_index(packages)
    packages_by_npm = {
        as_str(p.get("package_name")): p for p in packages if as_str(p.get("package_name"))
    }
    for plugin in plugins:
        npm_names = resolve_plugin_npm_packages(
            list(plugin.get("package_refs") or []),
            metadata_index,
            packages_by_npm,
            as_str(plugin.get("name")),
        )
        plugin["npm_packages"] = npm_names
        plugin["linked_packages"] = [
            packages_by_npm[npm] for npm in npm_names if npm in packages_by_npm
        ]


@dataclass
class SupportAlignmentReport:
    plugin_package_mismatches: list[dict[str, Any]] = field(default_factory=list)
    plugin_package_spread: list[dict[str, Any]] = field(default_factory=list)
    workspace_package_spread: list[dict[str, Any]] = field(default_factory=list)
    plugins_without_packages: list[dict[str, Any]] = field(default_factory=list)
    packages_without_plugin: list[dict[str, Any]] = field(default_factory=list)
    plugins_scanned: int = 0
    packages_scanned: int = 0

    def has_findings(self) -> bool:
        return bool(
            self.plugin_package_mismatches
            or self.plugin_package_spread
            or self.workspace_package_spread
            or self.plugins_without_packages
            or self.packages_without_plugin
        )


def _mismatch_direction(plugin_support: str, package_support: str) -> str:
    p_rank = support_rank(plugin_support)
    k_rank = support_rank(package_support)
    if p_rank == k_rank:
        return "same"
    if k_rank > p_rank:
        return "package_lagging"
    return "package_ahead"


def analyze_support_alignment(
    plugins: list[dict[str, Any]],
    packages: list[dict[str, Any]],
) -> SupportAlignmentReport:
    link_plugins_to_packages(plugins, packages)
    report = SupportAlignmentReport(
        plugins_scanned=len(plugins),
        packages_scanned=len(packages),
    )

    referenced_packages: set[str] = set()

    for plugin in plugins:
        linked = list(plugin.get("linked_packages") or [])
        if not linked:
            if plugin.get("package_refs"):
                report.plugins_without_packages.append(_plugin_summary(plugin))
            continue

        for pkg in linked:
            npm = as_str(pkg.get("package_name"))
            if npm:
                referenced_packages.add(npm)

        supports = {as_str(p.get("support")) for p in linked}
        if len(supports) > 1:
            report.plugin_package_spread.append(
                {
                    "plugin_name": as_str(plugin.get("name")),
                    "plugin_title": as_str(plugin.get("title")),
                    "plugin_support": as_str(plugin.get("support")),
                    "plugin_support_label": plugin.get("support_label", ""),
                    "packages": [_package_brief(p) for p in linked],
                    "support_levels": sorted(
                        {p.get("support_label", "") for p in linked},
                        key=lambda label: support_rank(
                            next(
                                (p["support"] for p in linked if p.get("support_label") == label),
                                "unknown",
                            )
                        ),
                    ),
                }
            )

        plugin_support = as_str(plugin.get("support"))
        for pkg in linked:
            package_support = as_str(pkg.get("support"))
            if package_support == plugin_support:
                continue
            direction = _mismatch_direction(plugin_support, package_support)
            report.plugin_package_mismatches.append(
                {
                    "plugin_name": as_str(plugin.get("name")),
                    "plugin_title": as_str(plugin.get("title")),
                    "plugin_support": plugin_support,
                    "plugin_support_label": plugin.get("support_label", ""),
                    "package_name": as_str(pkg.get("package_name")),
                    "package_title": as_str(pkg.get("title")),
                    "package_support": package_support,
                    "package_support_label": pkg.get("support_label", ""),
                    "workspace": as_str(pkg.get("workspace")),
                    "direction": direction,
                    "catalog_membership": as_str(plugin.get("catalog_membership_label")),
                }
            )

    by_workspace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pkg in packages:
        ws = as_str(pkg.get("workspace"))
        if ws:
            by_workspace[ws].append(pkg)

    for workspace, ws_packages in sorted(by_workspace.items()):
        supports = {as_str(p.get("support")) for p in ws_packages}
        if len(supports) <= 1:
            continue
        report.workspace_package_spread.append(
            {
                "workspace": workspace,
                "packages": [
                    _package_brief(p) for p in sorted(ws_packages, key=lambda x: x.get("title", ""))
                ],
                "support_levels": sorted(
                    {p.get("support_label", "") for p in ws_packages},
                    key=lambda label: support_rank(
                        next(
                            (p["support"] for p in ws_packages if p.get("support_label") == label),
                            "unknown",
                        )
                    ),
                ),
            }
        )

    for pkg in packages:
        npm = as_str(pkg.get("package_name"))
        if npm and npm not in referenced_packages:
            report.packages_without_plugin.append(_package_brief(pkg))

    report.packages_without_plugin.sort(
        key=lambda r: (r.get("workspace", ""), r.get("package_name", ""))
    )

    report.plugin_package_mismatches.sort(
        key=lambda r: (
            r.get("plugin_title", ""),
            r.get("direction", ""),
            r.get("package_name", ""),
        )
    )
    report.plugin_package_spread.sort(key=lambda r: r.get("plugin_title", ""))
    report.workspace_package_spread.sort(key=lambda r: r.get("workspace", ""))

    return report


def _plugin_summary(plugin: dict[str, Any]) -> dict[str, Any]:
    return {
        "plugin_name": as_str(plugin.get("name")),
        "plugin_title": as_str(plugin.get("title")),
        "plugin_support_label": plugin.get("support_label", ""),
        "package_refs": list(plugin.get("package_refs") or []),
        "file": as_str(plugin.get("file")),
    }


def _package_brief(pkg: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_name": as_str(pkg.get("package_name")),
        "title": as_str(pkg.get("title")),
        "support": as_str(pkg.get("support")),
        "support_label": pkg.get("support_label", ""),
        "workspace": as_str(pkg.get("workspace")),
        "role": as_str(pkg.get("role")),
    }


def alignment_payload(
    *,
    version: str,
    ref: str,
    source: dict[str, str],
    report: SupportAlignmentReport,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "mode": "support-alignment",
        "version": version,
        "ref": ref,
        "source": source,
        "counts": {
            "plugins_scanned": report.plugins_scanned,
            "packages_scanned": report.packages_scanned,
            "plugin_package_mismatches": len(report.plugin_package_mismatches),
            "plugin_package_spread": len(report.plugin_package_spread),
            "workspace_package_spread": len(report.workspace_package_spread),
            "plugins_without_packages": len(report.plugins_without_packages),
            "packages_without_plugin": len(report.packages_without_plugin),
        },
        "warnings": warnings,
        "plugin_package_mismatches": report.plugin_package_mismatches,
        "plugin_package_spread": report.plugin_package_spread,
        "workspace_package_spread": report.workspace_package_spread,
        "plugins_without_packages": report.plugins_without_packages,
        "packages_without_plugin": report.packages_without_plugin,
    }


def render_alignment_markdown(
    *,
    version: str,
    ref: str,
    source_caption: str,
    report: SupportAlignmentReport,
    warnings: list[str],
) -> str:
    lines = [
        f"# RHDH {version} support alignment review (`{ref}`)",
        "",
        "Flags **Plugin** catalog support vs linked **Package** metadata support, "
        "spread among packages for one plugin, and spread within a workspace. "
        "Review manually — some differences are intentional.",
        "",
        f"_Source: {source_caption}_",
        "",
        "| Finding | Count |",
        "|---|---|",
        f"| Plugin vs package support mismatch | {len(report.plugin_package_mismatches)} |",
        f"| Plugin with mixed package support levels | {len(report.plugin_package_spread)} |",
        f"| Workspace with mixed package support levels | {len(report.workspace_package_spread)} |",
        f"| Plugin lists packages but none resolved | {len(report.plugins_without_packages)} |",
        f"| Package metadata not linked from any plugin | {len(report.packages_without_plugin)} |",
        "",
        f"Scanned {report.plugins_scanned} plugins and {report.packages_scanned} packages.",
        "",
    ]

    if not report.has_findings():
        lines.append("No alignment findings — all linked plugin/package support levels match.")
        lines.append("")
    else:
        lines.append("**Manual review suggested** for the sections below.")
        lines.append("")

    if warnings:
        for note in warnings:
            lines.append(f"> {note}")
        lines.append("")

    _table(
        lines,
        "## Plugin vs package support mismatch",
        "Plugin `spec.support.level` differs from a linked Package `spec.support`. "
        "**package_lagging** = package is lower than the plugin (e.g. plugin GA, package TP).",
        report.plugin_package_mismatches,
        [
            "Plugin",
            "Plugin support",
            "Package",
            "Package support",
            "Workspace",
            "Direction",
            "Catalog",
        ],
        lambda r: [
            md_cell(r["plugin_title"]),
            md_cell(r["plugin_support_label"]),
            md_cell(r["package_name"]),
            md_cell(r["package_support_label"]),
            md_cell(r["workspace"]),
            md_cell(r["direction"].replace("_", " ")),
            md_cell(r.get("catalog_membership", "")),
        ],
    )

    _spread_section(
        lines,
        "## Plugin with mixed package support",
        "Linked packages for one plugin do not share the same support level.",
        report.plugin_package_spread,
        entity_key="plugin_title",
        support_key="plugin_support_label",
    )

    _spread_section(
        lines,
        "## Workspace with mixed package support",
        "Packages in the same overlay workspace disagree on support (may span multiple plugins).",
        report.workspace_package_spread,
        entity_key="workspace",
        support_key=None,
    )

    _table(
        lines,
        "## Plugins with unresolved package links",
        "Plugin YAML lists `spec.packages` but no matching Package metadata was found.",
        report.plugins_without_packages,
        ["Plugin", "Support", "Package refs", "Plugin YAML"],
        lambda r: [
            md_cell(r["plugin_title"]),
            md_cell(r["plugin_support_label"]),
            md_cell(", ".join(r.get("package_refs") or [])),
            md_cell(r.get("file", "")),
        ],
    )

    _table(
        lines,
        "## Packages not linked from any plugin",
        "Package metadata exists but no Plugin `spec.packages` entry resolved to it "
        "(modules, shared backends, or missing catalog links).",
        report.packages_without_plugin,
        ["Package", "Support", "Workspace", "Role"],
        lambda r: [
            md_cell(r["package_name"]),
            md_cell(r["support_label"]),
            md_cell(r["workspace"]),
            md_cell(r.get("role", "")),
        ],
    )

    return "\n".join(lines).rstrip() + "\n"


def _spread_section(
    lines: list[str],
    heading: str,
    blurb: str,
    rows: list[dict[str, Any]],
    *,
    entity_key: str,
    support_key: str | None,
) -> None:
    lines.extend([heading, "", blurb, ""])
    if not rows:
        lines.append("_None._")
        lines.append("")
        return
    for row in rows:
        title = row.get(entity_key, "")
        if support_key:
            lines.append(f"### {title} ({row.get(support_key, '')})")
        else:
            lines.append(f"### {title}")
        levels = ", ".join(row.get("support_levels") or [])
        lines.append(f"Support levels present: {levels}")
        lines.append("")
        lines.append("| Package | Support | Role |")
        lines.append("|---|---|---|")
        for pkg in row.get("packages") or []:
            lines.append(
                "| "
                + " | ".join(
                    [
                        md_cell(pkg.get("package_name", "")),
                        md_cell(pkg.get("support_label", "")),
                        md_cell(pkg.get("role", "")),
                    ]
                )
                + " |"
            )
        lines.append("")


def _table(
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
        lines.append("| " + " | ".join(cells(row)) + " |")
    lines.append("")
