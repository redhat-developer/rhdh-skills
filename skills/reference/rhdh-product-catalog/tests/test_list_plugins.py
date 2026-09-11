#!/usr/bin/env python3
"""Tests for product-catalog list_plugins."""

from __future__ import annotations

import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
LIB = SKILL_ROOT / "scripts" / "lib"
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(SCRIPTS))

import list_plugins as lp  # noqa: E402


class FixtureListingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugins = lp.sort_plugins(lp.load_from_workdir(FIXTURES))

    def test_skips_location_sample_and_package(self) -> None:
        titles = {p["title"] for p in self.plugins}
        self.assertNotIn("Plugin Title", titles)
        self.assertNotIn("Should Be Skipped", titles)
        files = {p["file"] for p in self.plugins}
        self.assertTrue(all(not f.endswith("all.yaml") for f in files))
        self.assertTrue(all(".sample" not in f for f in files))
        self.assertTrue(lp.is_plugin_path("catalog-entities/extensions/plugins/scorecard.yaml"))
        self.assertFalse(
            lp.is_plugin_path(
                "catalog-entities/extensions/plugins/1-boilerplate.yaml.sample"
            )
        )
        self.assertFalse(lp.is_plugin_path("catalog-entities/extensions/plugins/all.yaml"))

    def test_row_count(self) -> None:
        self.assertEqual(len(self.plugins), 7)

    def test_all_yaml_membership(self) -> None:
        in_cat = {p["name"] for p in self.plugins if p["in_catalog"]}
        packaged = {p["name"] for p in self.plugins if not p["in_catalog"]}
        self.assertEqual(
            in_cat, {"3scale", "scorecard", "bulk-import", "acr", "legacy-ga"}
        )
        self.assertEqual(packaged, {"partner-plugin", "mystery"})

    def test_catalog_then_support_then_title_order(self) -> None:
        titles = [p["title"] for p in self.plugins]
        self.assertEqual(
            titles,
            [
                "Bulk Import",
                "Legacy GA Plugin",
                "Azure Container Registry",
                "Scorecard",
                "APIs with 3scale",
                "Partner Plugin",
                "Mystery Plugin",
            ],
        )
        membership = [p["catalog_membership"] for p in self.plugins]
        self.assertEqual(membership[:5], [lp.IN_CATALOG] * 5)
        self.assertEqual(membership[5:], [lp.PACKAGED] * 2)

    def test_nested_and_legacy_support(self) -> None:
        bulk = next(p for p in self.plugins if p["name"] == "bulk-import")
        self.assertEqual(bulk["support"], "generally-available")
        legacy = next(p for p in self.plugins if p["name"] == "legacy-ga")
        self.assertEqual(legacy["support"], "generally-available")
        score = next(p for p in self.plugins if p["name"] == "scorecard")
        self.assertEqual(score["support_label"], "Developer Preview")

    def test_preinstalled_vs_custom(self) -> None:
        partner = next(p for p in self.plugins if p["name"] == "partner-plugin")
        self.assertEqual(partner["catalog_yaml"], "custom")
        self.assertFalse(partner["preinstalled"])
        scale = next(p for p in self.plugins if p["name"] == "3scale")
        self.assertEqual(scale["catalog_yaml"], "pre-installed")
        self.assertTrue(scale["preinstalled"])

    def test_author_provider_publisher(self) -> None:
        scale = next(p for p in self.plugins if p["name"] == "3scale")
        self.assertEqual(scale["author"], "Red Hat")
        self.assertEqual(scale["provider"], "Red Hat")
        self.assertEqual(scale["publisher"], "Red Hat")
        partner = next(p for p in self.plugins if p["name"] == "partner-plugin")
        self.assertEqual(partner["author"], "")
        self.assertEqual(partner["provider"], "Example")
        self.assertEqual(partner["publisher"], "")
        legacy = next(p for p in self.plugins if p["name"] == "legacy-ga")
        self.assertEqual(legacy["provider"], "")

    def test_unknown_support(self) -> None:
        mystery = next(p for p in self.plugins if p["name"] == "mystery")
        self.assertEqual(mystery["support"], "unknown")
        self.assertEqual(mystery["lifecycle"], "experimental")
        self.assertEqual(mystery["catalog_yaml"], "custom")

    def test_filters(self) -> None:
        ga = [
            p
            for p in self.plugins
            if lp.matches_filters(
                p,
                supports={"generally-available"},
                catalog_yaml=set(),
                membership=set(),
                names=[],
                lifecycles=[],
            )
        ]
        self.assertEqual({p["name"] for p in ga}, {"bulk-import", "legacy-ga"})
        custom = [
            p
            for p in self.plugins
            if lp.matches_filters(
                p,
                supports=set(),
                catalog_yaml={"custom"},
                membership=set(),
                names=[],
                lifecycles=[],
            )
        ]
        self.assertEqual({p["name"] for p in custom}, {"partner-plugin", "mystery"})
        packaged = [
            p
            for p in self.plugins
            if lp.matches_filters(
                p,
                supports=set(),
                catalog_yaml=set(),
                membership={lp.PACKAGED},
                names=[],
                lifecycles=[],
            )
        ]
        self.assertEqual({p["name"] for p in packaged}, {"partner-plugin", "mystery"})
        named = [
            p
            for p in self.plugins
            if lp.matches_filters(
                p,
                supports=set(),
                catalog_yaml=set(),
                membership=set(),
                names=["score"],
                lifecycles=[],
            )
        ]
        self.assertEqual([p["name"] for p in named], ["scorecard"])
        life = [
            p
            for p in self.plugins
            if lp.matches_filters(
                p,
                supports=set(),
                catalog_yaml=set(),
                membership=set(),
                names=[],
                lifecycles=["experimental"],
            )
        ]
        self.assertEqual([p["name"] for p in life], ["mystery"])


class CliTests(unittest.TestCase):
    def test_markdown_grouping(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = lp.main(["1.10", "--repo", str(FIXTURES), "--workdir"])
        self.assertEqual(code, 0)
        text = buf.getvalue()
        self.assertIn("# RHDH 1.10 plugins (`release-1.10`)", text)
        self.assertIn("## Included in the Catalog", text)
        self.assertIn("## Packaged, but Not in Catalog", text)
        self.assertLess(
            text.index("## Included in the Catalog"),
            text.index("## Packaged, but Not in Catalog"),
        )
        self.assertIn("### Generally Available", text)
        self.assertIn("### Community", text)
        self.assertIn("Partner Plugin", text)
        self.assertIn("| Title | Support | Lifecycle | Author | Provider | Publisher | Core OOTB | Plugin YAML |", text)
        self.assertIn("| APIs with 3scale | Community | active | Red Hat | Red Hat | Red Hat | — | pre-installed |", text)
        self.assertIn("| Partner Plugin | Community | active | — | Example | — | — | custom |", text)
        in_cat = text.index("## Included in the Catalog")
        packaged = text.index("## Packaged, but Not in Catalog")
        self.assertLess(text.index("Bulk Import"), packaged)
        self.assertGreater(text.index("Partner Plugin"), packaged)
        self.assertLess(in_cat, text.index("### Generally Available"))

    def test_filters_cli(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = lp.main(
                [
                    "1.10",
                    "--repo",
                    str(FIXTURES),
                    "--workdir",
                    "--not-in-catalog",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["filtered"])
        self.assertEqual(payload["catalog_membership"]["packaged"], 2)
        self.assertEqual(payload["catalog_membership"]["in-catalog"], 0)

    def test_bad_support(self) -> None:
        buf = StringIO()
        with redirect_stderr(buf):
            code = lp.main(["1.10", "--repo", str(FIXTURES), "--workdir", "--support", "nope"])
        self.assertEqual(code, lp.USAGE_EXIT)


class DiffLogicTests(unittest.TestCase):
    def test_support_lifecycle_added_removed(self) -> None:
        from diff import diff_items, plugin_key

        from_items = [
            {
                "name": "scorecard",
                "title": "Scorecard",
                "support": "dev-preview",
                "support_label": "Developer Preview",
                "lifecycle": "experimental",
                "file": "scorecard.yaml",
            },
            {
                "name": "old-plugin",
                "title": "Old Plugin",
                "support": "community",
                "support_label": "Community",
                "lifecycle": "active",
                "file": "old.yaml",
            },
        ]
        to_items = [
            {
                "name": "scorecard",
                "title": "Scorecard",
                "support": "generally-available",
                "support_label": "Generally Available",
                "lifecycle": "active",
                "file": "scorecard.yaml",
            },
            {
                "name": "new-plugin",
                "title": "New Plugin",
                "support": "community",
                "support_label": "Community",
                "lifecycle": "active",
                "file": "new.yaml",
            },
        ]
        report = diff_items(from_items, to_items, plugin_key)
        self.assertEqual([p["name"] for p in report.added], ["new-plugin"])
        self.assertEqual([p["name"] for p in report.removed], ["old-plugin"])
        self.assertEqual(report.changed[0]["changes"], ["support", "lifecycle"])


class DiffCliTests(unittest.TestCase):
    def test_diff_rejects_positional_version(self) -> None:
        buf = StringIO()
        with redirect_stderr(buf):
            code = lp.main(["1.10", "--diff", "1.9", "1.10"])
        self.assertEqual(code, lp.USAGE_EXIT)

    def test_diff_markdown_and_json(self) -> None:
        import tempfile

        from overlay_git_fixture import init_overlay_git

        def plugin_yaml(name: str, title: str, level: str, lifecycle: str) -> str:
            return (
                "apiVersion: extensions.backstage.io/v1alpha1\n"
                "kind: Plugin\n"
                "metadata:\n"
                f"  name: {name}\n"
                f"  title: {title}\n"
                "spec:\n"
                "  support:\n"
                "    provider: Red Hat\n"
                f"    level: {level}\n"
                f"  lifecycle: {lifecycle}\n"
            )

        def all_yaml(*names: str) -> str:
            targets = "\n".join(f"    - ./{n}.yaml" for n in names)
            return (
                "apiVersion: backstage.io/v1alpha1\n"
                "kind: Location\n"
                "spec:\n"
                "  targets:\n"
                f"{targets}\n"
            )

        with tempfile.TemporaryDirectory(dir=str(SKILL_ROOT / "tests")) as tmp:
            repo = init_overlay_git(
                Path(tmp) / "overlay",
                {
                    "release-1.9": {
                        "catalog-entities/extensions/plugins/scorecard.yaml": plugin_yaml(
                            "scorecard", "Scorecard", "dev-preview", "experimental"
                        ),
                        "catalog-entities/extensions/plugins/old-plugin.yaml": plugin_yaml(
                            "old-plugin", "Old Plugin", "community", "active"
                        ),
                        "catalog-entities/extensions/plugins/all.yaml": all_yaml(
                            "scorecard", "old-plugin"
                        ),
                    },
                    "release-1.10": {
                        "catalog-entities/extensions/plugins/scorecard.yaml": plugin_yaml(
                            "scorecard", "Scorecard", "generally-available", "active"
                        ),
                        "catalog-entities/extensions/plugins/new-plugin.yaml": plugin_yaml(
                            "new-plugin", "New Plugin", "community", "active"
                        ),
                        "catalog-entities/extensions/plugins/all.yaml": all_yaml(
                            "scorecard", "new-plugin"
                        ),
                    },
                },
            )
            buf = StringIO()
            with redirect_stdout(buf):
                code = lp.main(["--diff", "1.9", "1.10", "--repo", str(repo)])
            self.assertEqual(code, 0)
            text = buf.getvalue()
            self.assertIn("# RHDH plugin diff: 1.9 → 1.10", text)
            self.assertIn("## Support level changed", text)
            self.assertIn("## Newly added (in 1.10, not in 1.9)", text)
            self.assertIn("## Lifecycle changed", text)
            self.assertIn("## Removed (in 1.9, not in 1.10)", text)
            self.assertIn("Developer Preview → **Generally Available**", text)
            self.assertIn("experimental → **active**", text)
            self.assertIn("New Plugin", text)
            self.assertIn("Old Plugin", text)

            jbuf = StringIO()
            with redirect_stdout(jbuf):
                code = lp.main(["--diff", "1.9", "1.10", "--repo", str(repo), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(jbuf.getvalue())
            self.assertEqual(payload["mode"], "diff")
            self.assertEqual(payload["counts"]["added"], 1)
            self.assertEqual(payload["counts"]["removed"], 1)
            self.assertEqual(payload["counts"]["support"], 1)
            self.assertEqual(payload["counts"]["lifecycle"], 1)


if __name__ == "__main__":
    unittest.main()
