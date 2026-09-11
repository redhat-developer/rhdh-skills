#!/usr/bin/env python3
"""Tests for product-catalog list_packages."""

from __future__ import annotations

import json
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


class VersionToRefTests(unittest.TestCase):
    def test_stream_and_zstream(self) -> None:
        self.assertEqual(lp.version_to_ref("1.10"), "release-1.10")
        self.assertEqual(lp.version_to_ref("1.10.3"), "release-1.10")
        self.assertEqual(lp.version_to_ref("v1.9.0"), "release-1.9")

    def test_main_aliases(self) -> None:
        self.assertEqual(lp.version_to_ref("main"), "main")
        self.assertEqual(lp.version_to_ref("next"), "main")
        self.assertEqual(lp.version_to_ref("unreleased"), "main")

    def test_explicit_ref(self) -> None:
        self.assertEqual(lp.version_to_ref("release-1.10"), "release-1.10")
        self.assertEqual(lp.version_to_ref("catalog-index-release-1.10"), "catalog-index-release-1.10")


class SupportNormalizeTests(unittest.TestCase):
    def test_scalar_and_aliases(self) -> None:
        self.assertEqual(lp.normalize_support("generally-available"), "generally-available")
        self.assertEqual(lp.normalize_support("GA"), "generally-available")
        self.assertEqual(lp.normalize_support("production"), "generally-available")
        self.assertEqual(lp.normalize_support("Tech Preview"), "tech-preview")
        self.assertEqual(lp.normalize_support("dp"), "dev-preview")
        self.assertEqual(lp.normalize_support("community"), "community")

    def test_nested(self) -> None:
        self.assertEqual(
            lp.normalize_support({"provider": "Red Hat", "level": "tech-preview"}),
            "tech-preview",
        )

    def test_missing(self) -> None:
        self.assertEqual(lp.normalize_support(None), "unknown")
        self.assertEqual(lp.normalize_support("not-a-level"), "unknown")


class FixtureListingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packages = lp.sort_packages(lp.load_from_workdir(FIXTURES))

    def test_skips_plugin_kind(self) -> None:
        kinds = {p["kind"] for p in self.packages}
        self.assertEqual(kinds, {"Package"})
        titles = {p["title"] for p in self.packages}
        self.assertNotIn("Should Be Skipped", titles)

    def test_row_count(self) -> None:
        # 2 adoption-insights + scorecard + todo + example-tp + mystery
        self.assertEqual(len(self.packages), 6)

    def test_workspace_then_support_order(self) -> None:
        workspaces = [p["workspace"] for p in self.packages]
        self.assertEqual(
            workspaces,
            [
                "adoption-insights",
                "adoption-insights",
                "example-tp",
                "mystery",
                "scorecard",
                "todo",
            ],
        )
        ai = [p for p in self.packages if p["workspace"] == "adoption-insights"]
        self.assertEqual(ai[0]["title"], "Adoption Insights Backend")
        self.assertEqual(ai[1]["title"], "Adoption Insights Frontend")

    def test_fields(self) -> None:
        fe = next(p for p in self.packages if p["title"] == "Adoption Insights Frontend")
        self.assertEqual(fe["package_name"], "@red-hat-developer-hub/backstage-plugin-adoption-insights")
        self.assertEqual(fe["support_label"], "Generally Available")
        self.assertEqual(fe["backstage"], "1.52.0")
        self.assertEqual(fe["role"], "frontend-plugin")
        self.assertEqual(fe["version"], "0.9.1")
        self.assertEqual(fe["author"], "Red Hat")
        self.assertEqual(fe["lifecycle"], "active")
        self.assertIn("rhdh-plugins", fe["source"])

    def test_annotation_source_fallback(self) -> None:
        todo = next(p for p in self.packages if p["workspace"] == "todo")
        self.assertEqual(
            todo["source"],
            "https://github.com/backstage/community-plugins/tree/main/workspaces/todo",
        )

    def test_nested_support(self) -> None:
        tp = next(p for p in self.packages if p["workspace"] == "example-tp")
        self.assertEqual(tp["support"], "tech-preview")
        self.assertEqual(tp["support_label"], "Tech Preview")

    def test_unknown_support(self) -> None:
        mystery = next(p for p in self.packages if p["workspace"] == "mystery")
        self.assertEqual(mystery["support"], "unknown")
        self.assertEqual(mystery["source"], "")

    def test_filters(self) -> None:
        ga = [
            p
            for p in self.packages
            if lp.matches_filters(p, {"generally-available"}, [], [])
        ]
        self.assertEqual(len(ga), 2)
        score = [
            p
            for p in self.packages
            if lp.matches_filters(p, set(), ["score"], [])
        ]
        self.assertEqual([p["workspace"] for p in score], ["scorecard"])
        pkg = [
            p
            for p in self.packages
            if lp.matches_filters(p, set(), [], ["plugin-todo"])
        ]
        self.assertEqual(len(pkg), 1)


class CliTests(unittest.TestCase):
    def test_markdown_and_json(self) -> None:
        from io import StringIO
        from contextlib import redirect_stdout

        buf = StringIO()
        with redirect_stdout(buf):
            code = lp.main(
                ["1.10", "--repo", str(FIXTURES), "--workdir", "--json"]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["scanned"], 6)
        self.assertEqual(payload["total"], 6)

    def test_compare_txt_cli(self) -> None:
        from io import StringIO
        from contextlib import redirect_stdout

        buf = StringIO()
        with redirect_stdout(buf):
            code = lp.main(
                [
                    "1.10",
                    "--repo",
                    str(FIXTURES),
                    "--workdir",
                    "--compare-txt",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["mode"], "compare-txt")
        self.assertFalse(payload["aligned"])
        self.assertEqual(payload["counts"]["txt_supported_mismatches"], 1)
        self.assertEqual(payload["counts"]["packages"], 6)

    def test_cli_markdown_grouping(self) -> None:
        from io import StringIO
        from contextlib import redirect_stdout

        buf = StringIO()
        with redirect_stdout(buf):
            code = lp.main(["1.10", "--repo", str(FIXTURES), "--workdir"])
        self.assertEqual(code, 0)
        text = buf.getvalue()
        self.assertIn("# RHDH 1.10 packages (`release-1.10`)", text)
        self.assertIn("## adoption-insights", text)
        self.assertIn("Generally Available", text)
        self.assertIn("Developer Preview", text)
        self.assertLess(text.index("## adoption-insights"), text.index("## scorecard"))
        self.assertIn("Unknown", text)
        self.assertIn("missing or unrecognized spec.support", text)

    def test_support_filter_cli(self) -> None:
        from io import StringIO
        from contextlib import redirect_stdout

        buf = StringIO()
        with redirect_stdout(buf):
            code = lp.main(
                ["1.10", "--repo", str(FIXTURES), "--workdir", "--support", "ga", "--json"]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["total"], 2)
        self.assertTrue(payload["filtered"])
        self.assertEqual(payload["counts"]["generally-available"], 2)

    def test_bad_support(self) -> None:
        from io import StringIO
        from contextlib import redirect_stderr

        buf = StringIO()
        with redirect_stderr(buf):
            code = lp.main(["1.10", "--repo", str(FIXTURES), "--workdir", "--support", "nope"])
        self.assertEqual(code, lp.USAGE_EXIT)


class CatFileBatchTests(unittest.TestCase):
    def test_parse_blobs_and_missing(self) -> None:
        import overlay_repo as ov

        first = b"alpha\ntext"
        second = b"beta"
        buf = (
            f"aaa blob {len(first)}\n".encode()
            + first
            + b"\n"
            + b"release-1.9:gone.yaml missing\n"
            + f"bbb blob {len(second)}\n".encode()
            + second
            + b"\n"
        )
        got = ov.parse_cat_file_batch(buf, ["one.yaml", "gone.yaml", "two.yaml"])
        self.assertEqual(got["one.yaml"], "alpha\ntext")
        self.assertEqual(got["two.yaml"], "beta")
        self.assertNotIn("gone.yaml", got)

    def test_read_files_skips_non_metadata_workspace_paths(self) -> None:
        import tempfile

        import overlay_repo as ov
        from overlay_git_fixture import init_overlay_git

        pkg = """\
apiVersion: extensions.backstage.io/v1alpha1
kind: Package
metadata:
  name: scorecard
  title: Scorecard
spec:
  packageName: "@example/scorecard"
  support: community
  lifecycle: active
"""
        with tempfile.TemporaryDirectory(dir=str(SKILL_ROOT / "tests")) as tmp:
            repo = init_overlay_git(
                Path(tmp) / "overlay",
                {
                    "release-1.10": {
                        "workspaces/scorecard/metadata/scorecard.yaml": pkg,
                        "workspaces/scorecard/source.json": '{"repo":"https://example.com"}',
                        "workspaces/scorecard/plugins/overlay/README.md": "not metadata",
                    }
                },
            )
            listed = ov.list_via_git(repo, "release-1.10", "workspaces")
            self.assertGreater(len(listed), 1)
            packages, _ = lp.load_from_git(repo, "release-1.10")
            self.assertEqual(len(packages), 1)
            self.assertEqual(packages[0]["package_name"], "@example/scorecard")


class DiffLogicTests(unittest.TestCase):
    def test_support_lifecycle_added_removed(self) -> None:
        from diff import diff_items, package_key

        from_items = [
            {
                "package_name": "@a/score",
                "title": "Scorecard",
                "support": "community",
                "support_label": "Community",
                "lifecycle": "experimental",
                "file": "a.yaml",
                "workspace": "scorecard",
            },
            {
                "package_name": "@a/old",
                "title": "Old Package",
                "support": "generally-available",
                "support_label": "Generally Available",
                "lifecycle": "active",
                "file": "b.yaml",
                "workspace": "old",
            },
            {
                "package_name": "@a/same",
                "title": "Same",
                "support": "community",
                "support_label": "Community",
                "lifecycle": "Active",
                "file": "c.yaml",
                "workspace": "same",
            },
        ]
        to_items = [
            {
                "package_name": "@a/score",
                "title": "Scorecard",
                "support": "generally-available",
                "support_label": "Generally Available",
                "lifecycle": "active",
                "file": "a.yaml",
                "workspace": "scorecard",
            },
            {
                "package_name": "@a/new",
                "title": "New Package",
                "support": "community",
                "support_label": "Community",
                "lifecycle": "active",
                "file": "d.yaml",
                "workspace": "new",
            },
            {
                "package_name": "@a/same",
                "title": "Same",
                "support": "community",
                "support_label": "Community",
                "lifecycle": "active",
                "file": "c.yaml",
                "workspace": "same",
            },
        ]
        report = diff_items(from_items, to_items, package_key)
        self.assertEqual(report.unchanged, 1)
        self.assertEqual([p["title"] for p in report.added], ["New Package"])
        self.assertEqual([p["title"] for p in report.removed], ["Old Package"])
        self.assertEqual(len(report.support_changes()), 1)
        self.assertEqual(len(report.lifecycle_changes()), 1)
        self.assertEqual(report.changed[0]["changes"], ["support", "lifecycle"])

    def test_restrict_keeps_identity_if_either_side_matches(self) -> None:
        from diff import package_key, restrict_to_matching_identities

        from_items = [
            {"package_name": "@a/score", "workspace": "other", "title": "Scorecard"},
        ]
        to_items = [
            {"package_name": "@a/score", "workspace": "scorecard", "title": "Scorecard"},
        ]
        kept_from, kept_to = restrict_to_matching_identities(
            from_items,
            to_items,
            package_key,
            lambda pkg: "score" in pkg["workspace"],
        )
        self.assertEqual(len(kept_from), 1)
        self.assertEqual(len(kept_to), 1)


class DiffCliTests(unittest.TestCase):
    def test_diff_rejects_workdir(self) -> None:
        from io import StringIO
        from contextlib import redirect_stderr

        buf = StringIO()
        with redirect_stderr(buf):
            code = lp.main(["--diff", "1.9", "1.10", "--repo", str(FIXTURES), "--workdir"])
        self.assertEqual(code, lp.USAGE_EXIT)

    def test_diff_markdown_and_json(self) -> None:
        import tempfile
        from contextlib import redirect_stdout
        from io import StringIO

        from overlay_git_fixture import init_overlay_git

        score_from = """\
apiVersion: extensions.backstage.io/v1alpha1
kind: Package
metadata:
  name: scorecard
  title: Scorecard
spec:
  packageName: "@red-hat-developer-hub/backstage-plugin-scorecard"
  support: community
  lifecycle: experimental
"""
        score_to = """\
apiVersion: extensions.backstage.io/v1alpha1
kind: Package
metadata:
  name: scorecard
  title: Scorecard
spec:
  packageName: "@red-hat-developer-hub/backstage-plugin-scorecard"
  support: generally-available
  lifecycle: active
"""
        old = """\
apiVersion: extensions.backstage.io/v1alpha1
kind: Package
metadata:
  name: old-pkg
  title: Old Package
spec:
  packageName: "@example/old"
  support: generally-available
  lifecycle: active
"""
        new = """\
apiVersion: extensions.backstage.io/v1alpha1
kind: Package
metadata:
  name: new-pkg
  title: New Package
spec:
  packageName: "@example/new"
  support: community
  lifecycle: active
"""
        with tempfile.TemporaryDirectory(dir=str(SKILL_ROOT / "tests")) as tmp:
            repo = init_overlay_git(
                Path(tmp) / "overlay",
                {
                    "release-1.9": {
                        "workspaces/scorecard/metadata/scorecard.yaml": score_from,
                        "workspaces/old/metadata/old.yaml": old,
                    },
                    "release-1.10": {
                        "workspaces/scorecard/metadata/scorecard.yaml": score_to,
                        "workspaces/new/metadata/new.yaml": new,
                    },
                },
            )
            buf = StringIO()
            with redirect_stdout(buf):
                code = lp.main(["--diff", "1.9", "1.10", "--repo", str(repo)])
            self.assertEqual(code, 0)
            text = buf.getvalue()
            self.assertIn("# RHDH package diff: 1.9 → 1.10", text)
            self.assertIn("## Support level changed", text)
            self.assertIn("## Newly added (in 1.10, not in 1.9)", text)
            self.assertIn("## Lifecycle changed", text)
            self.assertIn("## Removed (in 1.9, not in 1.10)", text)
            self.assertIn("Community → **Generally Available**", text)
            self.assertIn("experimental → **active**", text)
            self.assertIn("New Package", text)
            self.assertIn("Old Package", text)
            self.assertLess(text.index("## Support level changed"), text.index("## Newly added"))
            self.assertLess(text.index("## Newly added"), text.index("## Lifecycle changed"))

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
            self.assertEqual(payload["counts"]["unchanged"], 0)


if __name__ == "__main__":
    unittest.main()
