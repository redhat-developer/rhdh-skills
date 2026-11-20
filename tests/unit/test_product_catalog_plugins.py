#!/usr/bin/env python3
"""Tests for product-catalog list_plugins."""

from __future__ import annotations

import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = PROJECT_ROOT / "skills" / "release" / "rhdh-product-catalog"
SCRIPTS = SKILL_DIR / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "product_catalog"
sys.path.insert(0, str(SCRIPTS / "lib"))
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import list_plugins as lp  # noqa: E402
import overlay_repo as repo_mod  # noqa: E402


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
            lp.is_plugin_path("catalog-entities/extensions/plugins/1-boilerplate.yaml.sample")
        )
        self.assertFalse(lp.is_plugin_path("catalog-entities/extensions/plugins/all.yaml"))

    def test_row_count(self) -> None:
        self.assertEqual(len(self.plugins), 7)

    def test_all_yaml_membership(self) -> None:
        in_cat = {p["name"] for p in self.plugins if p["in_catalog"]}
        packaged = {p["name"] for p in self.plugins if not p["in_catalog"]}
        self.assertEqual(in_cat, {"3scale", "scorecard", "bulk-import", "acr", "legacy-ga"})
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

    def test_tags_loaded(self) -> None:
        scale = next(p for p in self.plugins if p["name"] == "3scale")
        self.assertEqual(scale["tags"], ["openshift", "integration"])

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
    def test_cli_grouping(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = lp.main(["1.10", "--repo", str(FIXTURES), "--workdir", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["catalog_membership"], {"in-catalog": 5, "packaged": 2})
        self.assertEqual(payload["catalog_yaml"], {"pre-installed": 5, "custom": 2})
        self.assertEqual(
            [(plugin["name"], plugin["catalog_membership"]) for plugin in payload["plugins"]],
            [
                ("bulk-import", "in-catalog"),
                ("legacy-ga", "in-catalog"),
                ("acr", "in-catalog"),
                ("scorecard", "in-catalog"),
                ("3scale", "in-catalog"),
                ("partner-plugin", "packaged"),
                ("mystery", "packaged"),
            ],
        )

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

        from product_catalog_git_fixture import init_overlay_git

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
                f"apiVersion: backstage.io/v1alpha1\nkind: Location\nspec:\n  targets:\n{targets}\n"
            )

        with tempfile.TemporaryDirectory() as tmp:
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
                code = lp.main(["--diff", "1.9", "1.10", "--repo", str(repo), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["mode"], "diff")
            self.assertEqual(payload["counts"]["added"], 1)
            self.assertEqual(payload["counts"]["removed"], 1)
            self.assertEqual(payload["counts"]["support"], 1)
            self.assertEqual(payload["counts"]["lifecycle"], 1)


class SearchTests(unittest.TestCase):
    """--search answers an availability question from both catalog tiles and packages."""

    def test_search_shows_plugins_and_packages(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = lp.main(
                [
                    "1.10",
                    "--repo",
                    str(FIXTURES),
                    "--workdir",
                    "--search",
                    "scorecard",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual([plugin["name"] for plugin in payload["plugins"]], ["scorecard"])
        self.assertEqual(
            [package["package_name"] for package in payload["packages"]],
            ["@red-hat-developer-hub/backstage-plugin-scorecard"],
        )

    def test_search_reports_when_no_package_matches(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = lp.main(
                ["1.10", "--repo", str(FIXTURES), "--workdir", "--search", "3scale", "--json"]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual([plugin["name"] for plugin in payload["plugins"]], ["3scale"])
        self.assertEqual(payload["packages"], [])

    def test_search_json_includes_packages(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = lp.main(
                ["1.10", "--repo", str(FIXTURES), "--workdir", "--search", "todo", "--json"]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual([p["name"] for p in payload["plugins"]], [])
        self.assertEqual(
            [p["package_name"] for p in payload["packages"]],
            ["@backstage-community/plugin-todo"],
        )
        self.assertTrue(payload["filtered"])

    def test_search_matches_tags_but_name_filter_does_not(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = lp.main(["1.10", "--repo", str(FIXTURES), "--workdir", "--search", "openshift"])
        self.assertEqual(code, 0)
        self.assertIn("APIs with 3scale", buf.getvalue())

        nbuf = StringIO()
        with redirect_stdout(nbuf):
            lp.main(["1.10", "--repo", str(FIXTURES), "--workdir", "--name", "openshift"])
        self.assertNotIn("APIs with 3scale", nbuf.getvalue())

    def test_search_without_terms_leaves_output_unchanged(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            lp.main(["1.10", "--repo", str(FIXTURES), "--workdir"])
        self.assertNotIn("## Matching packages", buf.getvalue())


class TarballDiffCoreTests(unittest.TestCase):
    """Each side of a --diff reads its own default.packages.yaml."""

    @staticmethod
    def _write_side(root: Path, ref: str) -> Path:
        name = "old-plugin" if ref == "release-1.9" else "new-plugin"
        title = "Old Plugin" if ref == "release-1.9" else "New Plugin"
        ootb = "disabled" if ref == "release-1.9" else "enabled"
        files = {
            f"catalog-entities/extensions/plugins/{name}.yaml": (
                "apiVersion: extensions.backstage.io/v1alpha1\n"
                "kind: Plugin\n"
                "metadata:\n"
                f"  name: {name}\n"
                f"  title: {title}\n"
                "spec:\n"
                "  support:\n"
                "    level: community\n"
                "  lifecycle: active\n"
                "  packages:\n"
                f"    - {name}-pkg\n"
            ),
            f"workspaces/{name}/metadata/{name}.yaml": (
                "apiVersion: extensions.backstage.io/v1alpha1\n"
                "kind: Package\n"
                "metadata:\n"
                f"  name: {name}-pkg\n"
                f"  title: {title} Package\n"
                "spec:\n"
                f'  packageName: "@acme/{name}"\n'
                "  support: community\n"
                "  lifecycle: active\n"
            ),
            "default.packages.yaml": (
                "packages:\n"
                f"  {ootb}:\n"
                f"    - package: '@acme/{name}'\n"
                '      support: "community"\n'
            ),
        }
        for rel, content in files.items():
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        return root

    def test_added_and_removed_rows_use_their_own_core_list(self) -> None:
        def fake_fetch(ref: str, dest: Path) -> Path:
            return self._write_side(dest, ref)

        buf = StringIO()
        with mock.patch.object(repo_mod, "discover_overlay_repo", return_value=None):
            with mock.patch.object(
                repo_mod, "remote_release_branches", return_value={(1, 9), (1, 10)}
            ):
                with mock.patch.object(repo_mod, "fetch_overlay_tarball", side_effect=fake_fetch):
                    with redirect_stdout(buf):
                        code = lp.main(["--diff", "1.9", "1.10", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        added = {p["title"]: p["core_ootb"] for p in payload["added"]}
        removed = {p["title"]: p["core_ootb"] for p in payload["removed"]}
        self.assertEqual(added, {"New Plugin": "enabled"})
        self.assertEqual(removed, {"Old Plugin": "disabled"})


if __name__ == "__main__":
    unittest.main()
