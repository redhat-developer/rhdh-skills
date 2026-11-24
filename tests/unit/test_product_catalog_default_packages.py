#!/usr/bin/env python3
"""Tests for default.packages.yaml core enrichment."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = PROJECT_ROOT / "skills" / "release" / "rhdh-product-catalog"
SCRIPTS = SKILL_DIR / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "product_catalog"
sys.path.insert(0, str(SCRIPTS / "lib"))
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import list_packages as lp  # noqa: E402
from default_packages import (  # noqa: E402
    CoreIndex,
    plugin_package_refs,
)


class DefaultPackagesParseTests(unittest.TestCase):
    def test_parse_enabled_and_disabled(self) -> None:
        core = CoreIndex.parse((FIXTURES / "default.packages.yaml").read_text())
        self.assertEqual(len(core), 3)
        score = core.get("@red-hat-developer-hub/backstage-plugin-scorecard")
        self.assertIsNotNone(score)
        assert score is not None
        self.assertEqual(score.ootb, "enabled")
        fe = core.get("@red-hat-developer-hub/backstage-plugin-adoption-insights")
        assert fe is not None
        self.assertEqual(fe.ootb, "disabled")


class PackageCoreEnrichmentTests(unittest.TestCase):
    def test_fixture_packages_get_core_labels(self) -> None:
        from default_packages import enrich_packages_with_core

        core = CoreIndex.parse((FIXTURES / "default.packages.yaml").read_text())
        packages = lp.sort_packages(lp.load_from_workdir(FIXTURES))
        enrich_packages_with_core(packages, core)
        score = next(
            p
            for p in packages
            if p["package_name"] == "@red-hat-developer-hub/backstage-plugin-scorecard"
        )
        self.assertTrue(score["core"])
        self.assertEqual(score["core_ootb"], "enabled")
        self.assertEqual(score["core_ootb_label"], "enabled OOTB")
        todo = next(p for p in packages if p["workspace"] == "todo")
        self.assertFalse(todo["core"])


class PluginPackageRefsTests(unittest.TestCase):
    def test_regex_fallback_for_packages_list(self) -> None:
        text = """\
apiVersion: extensions.backstage.io/v1alpha1
kind: Plugin
metadata:
  name: signals-frontend
spec:
  packages:
  - backstage-plugin-signals
  - backstage-plugin-signals-backend
"""
        doc = {"spec": {}}
        refs = plugin_package_refs(doc, text)
        self.assertEqual(
            refs,
            ["backstage-plugin-signals", "backstage-plugin-signals-backend"],
        )


if __name__ == "__main__":
    unittest.main()
