#!/usr/bin/env python3
"""Tests for package txt list comparison."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
LIB = SKILL_ROOT / "scripts" / "lib"
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(SCRIPTS))

import list_packages as lp  # noqa: E402
from package_txt_compare import (  # noqa: E402
    compare_packages_to_txt,
    load_txt_files_from_root,
    packages_for_txt_path,
    parse_txt_paths,
)


class ParseTxtTests(unittest.TestCase):
    def test_skips_comments_and_blanks(self) -> None:
        text = "# header\ntodo/plugins/todo\n\n# tail\nscorecard/plugins/scorecard\n"
        self.assertEqual(
            parse_txt_paths(text),
            {"todo/plugins/todo", "scorecard/plugins/scorecard"},
        )


class CompareFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packages = lp.sort_packages(lp.load_from_workdir(FIXTURES))
        comm, supp = load_txt_files_from_root(FIXTURES)
        assert comm is not None and supp is not None
        self.report = compare_packages_to_txt(
            self.packages, community_text=comm, supported_text=supp
        )

    def test_finds_supported_mismatch_for_community_package(self) -> None:
        mismatches = self.report.txt_supported_mismatches
        pkgs = {m["package_name"] for m in mismatches}
        self.assertIn("@backstage-community/plugin-todo", pkgs)

    def test_community_txt_paths_align(self) -> None:
        self.assertEqual(self.report.txt_community_mismatches, [])

    def test_mapped_package_count(self) -> None:
        self.assertGreater(self.report.mapped_package_count, 0)
        self.assertLess(self.report.mapped_package_count, self.report.total_packages)

    def test_maps_adoption_insights_paths(self) -> None:
        from package_txt_compare import index_by_workspace

        hits = packages_for_txt_path(
            "adoption-insights/plugins/adoption-insights",
            index_by_workspace(self.packages),
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(
            hits[0]["package_name"],
            "@red-hat-developer-hub/backstage-plugin-adoption-insights",
        )


if __name__ == "__main__":
    unittest.main()
