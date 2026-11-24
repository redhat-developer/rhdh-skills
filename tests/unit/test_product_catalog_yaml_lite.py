#!/usr/bin/env python3
"""Direct tests for the product-catalog YAML subset parser."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIB = PROJECT_ROOT / "skills" / "release" / "rhdh-product-catalog" / "scripts" / "lib"
sys.path.insert(0, str(LIB))

from yaml_lite import parse_yaml  # noqa: E402


class YamlLiteTests(unittest.TestCase):
    def test_dotted_versions_remain_strings(self) -> None:
        doc = parse_yaml("spec:\n  version: 1.10\n  supportedVersions: 1.0\n  count: 2\n")
        self.assertEqual(doc["spec"]["version"], "1.10")
        self.assertEqual(doc["spec"]["supportedVersions"], "1.0")
        self.assertEqual(doc["spec"]["count"], 2)

    def test_quoted_strings_and_block_scalars(self) -> None:
        doc = parse_yaml(
            "metadata:\n  title: 'Quoted title'\n  description: >-\n    Line one\n    Line two\n"
        )
        self.assertEqual(doc["metadata"]["title"], "Quoted title")
        self.assertIn("Line one", doc["metadata"]["description"])
        self.assertIn("Line two", doc["metadata"]["description"])

    def test_multiple_documents_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_yaml("kind: Package\n---\nkind: Other\n")

    def test_anchors_and_merge_keys_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_yaml("base: &base\n  value: one\nchild:\n  <<: *base\n")

    def test_non_empty_flow_collections_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_yaml("spec:\n  packages: [one, two]\n")


if __name__ == "__main__":
    unittest.main()
