#!/usr/bin/env python3
"""Tests for product-catalog diff classification."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIB = PROJECT_ROOT / "skills" / "release" / "rhdh-product-catalog" / "scripts" / "lib"
sys.path.insert(0, str(LIB))

from diff import diff_items, package_key  # noqa: E402


class SupportMetadataDiffTests(unittest.TestCase):
    @staticmethod
    def _item(name: str, support: str) -> dict:
        return {
            "package_name": name,
            "title": name,
            "support": support,
            "support_label": support,
            "lifecycle": "active",
        }

    def test_unknown_to_known_is_metadata_appeared(self) -> None:
        report = diff_items(
            [self._item("@example/plugin", "unknown")],
            [self._item("@example/plugin", "generally-available")],
            package_key,
        )
        self.assertEqual(report.support_changes(), [])
        self.assertEqual(len(report.support_metadata_appeared()), 1)
        self.assertEqual(report.support_metadata_disappeared(), [])

    def test_known_to_unknown_is_metadata_disappeared(self) -> None:
        report = diff_items(
            [self._item("@example/plugin", "generally-available")],
            [self._item("@example/plugin", "unknown")],
            package_key,
        )
        self.assertEqual(report.support_changes(), [])
        self.assertEqual(report.support_metadata_appeared(), [])
        self.assertEqual(len(report.support_metadata_disappeared()), 1)


if __name__ == "__main__":
    unittest.main()
