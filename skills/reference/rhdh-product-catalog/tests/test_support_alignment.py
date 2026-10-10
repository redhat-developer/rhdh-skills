#!/usr/bin/env python3
"""Tests for plugin/package support alignment."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
LIB = SKILL_ROOT / "scripts" / "lib"
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(SCRIPTS))

from support_alignment import analyze_support_alignment  # noqa: E402


def _pkg(
    *,
    workspace: str,
    name: str,
    title: str,
    support: str,
    package_name: str,
    role: str = "frontend-plugin",
) -> dict:
    labels = {
        "generally-available": "Generally Available",
        "tech-preview": "Tech Preview",
        "dev-preview": "Developer Preview",
        "community": "Community",
    }
    return {
        "workspace": workspace,
        "name": name,
        "title": title,
        "support": support,
        "support_label": labels[support],
        "package_name": package_name,
        "role": role,
        "file": f"workspaces/{workspace}/metadata/{name}.yaml",
    }


def _plugin(
    *,
    name: str,
    title: str,
    support: str,
    package_refs: list[str],
) -> dict:
    labels = {
        "generally-available": "Generally Available",
        "tech-preview": "Tech Preview",
        "dev-preview": "Developer Preview",
        "community": "Community",
    }
    return {
        "name": name,
        "title": title,
        "support": support,
        "support_label": labels[support],
        "package_refs": package_refs,
        "catalog_membership_label": "Included in the Catalog",
        "file": f"catalog-entities/extensions/plugins/{name}.yaml",
    }


class SupportAlignmentTests(unittest.TestCase):
    def test_flags_plugin_vs_package_mismatch(self) -> None:
        plugins = [
            _plugin(
                name="orchestrator",
                title="Orchestrator",
                support="generally-available",
                package_refs=["rhdh-bsp-orchestrator", "rhdh-bsp-orchestrator-backend"],
            )
        ]
        packages = [
            _pkg(
                workspace="orchestrator",
                name="rhdh-bsp-orchestrator",
                title="Orchestrator FE",
                support="generally-available",
                package_name="@red-hat-developer-hub/backstage-plugin-orchestrator",
            ),
            _pkg(
                workspace="orchestrator",
                name="rhdh-bsp-orchestrator-backend",
                title="Orchestrator BE",
                support="tech-preview",
                package_name="@red-hat-developer-hub/backstage-plugin-orchestrator-backend",
                role="backend-plugin",
            ),
        ]
        report = analyze_support_alignment(plugins, packages)
        self.assertEqual(len(report.plugin_package_mismatches), 1)
        self.assertEqual(report.plugin_package_mismatches[0]["direction"], "package_lagging")
        self.assertEqual(len(report.plugin_package_spread), 1)

    def test_aligned_plugin_has_no_mismatch(self) -> None:
        plugins = [
            _plugin(
                name="scorecard",
                title="Scorecard",
                support="dev-preview",
                package_refs=["rhdh-backstage-plugin-scorecard"],
            )
        ]
        packages = [
            _pkg(
                workspace="scorecard",
                name="rhdh-backstage-plugin-scorecard",
                title="Scorecard",
                support="dev-preview",
                package_name="@red-hat-developer-hub/backstage-plugin-scorecard",
            )
        ]
        report = analyze_support_alignment(plugins, packages)
        self.assertEqual(report.plugin_package_mismatches, [])
        self.assertEqual(report.plugin_package_spread, [])


if __name__ == "__main__":
    unittest.main()
