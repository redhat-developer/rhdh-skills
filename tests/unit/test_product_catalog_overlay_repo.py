#!/usr/bin/env python3
"""Tests for product-catalog overlay transport: tarball download and extraction."""

from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT_ROOT / "skills" / "release" / "rhdh-product-catalog" / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))
sys.path.insert(0, str(SCRIPTS))

import list_plugins as lp  # noqa: E402
import overlay_repo as repo_mod  # noqa: E402
from product_catalog_git_fixture import init_overlay_git  # noqa: E402


def overlay_tarball(members: dict[str, str]) -> bytes:
    """Build a GitHub-shaped tarball: one top-level directory above every path."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for rel, content in members.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(f"rhdh-plugin-export-overlays-abc123/{rel}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def plugin_yaml(name: str, title: str, support: str) -> str:
    return (
        "apiVersion: extensions.backstage.io/v1alpha1\n"
        "kind: Plugin\n"
        "metadata:\n"
        f"  name: {name}\n"
        f"  title: {title}\n"
        "spec:\n"
        "  support:\n"
        f"    level: {support}\n"
        "  lifecycle: active\n"
    )


class ExtractTests(unittest.TestCase):
    def test_keeps_only_the_paths_the_scripts_read(self) -> None:
        payload = overlay_tarball(
            {
                "workspaces/scorecard/metadata/scorecard.yaml": "name: scorecard\n",
                "catalog-entities/extensions/plugins/scorecard.yaml": plugin_yaml(
                    "scorecard", "Scorecard", "community"
                ),
                "default.packages.yaml": "packages:\n  enabled:\n",
                "rhdh-community-packages.txt": "a\n",
                "rhdh-supported-packages.txt": "b\n",
                "README.md": "not read\n",
                "workspaces/scorecard/catalog-info.yaml": "not read\n",
                "catalog-entities/extensions/plugins/nested/other.yaml": "not read\n",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = repo_mod.extract_overlay_tarball(payload, Path(tmp) / "overlay")
            written = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
        self.assertEqual(
            written,
            [
                "catalog-entities/extensions/plugins/scorecard.yaml",
                "default.packages.yaml",
                "rhdh-community-packages.txt",
                "rhdh-supported-packages.txt",
                "workspaces/scorecard/metadata/scorecard.yaml",
            ],
        )


class FetchTests(unittest.TestCase):
    def test_downloads_the_ref_and_extracts_it(self) -> None:
        payload = overlay_tarball({"default.packages.yaml": "packages:\n  enabled:\n"})
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = payload
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "overlay"
            with mock.patch("overlay_repo.urllib.request.urlopen", return_value=response) as opened:
                repo_mod.fetch_overlay_tarball("release-2.1", dest)
            url = opened.call_args.args[0].full_url
            self.assertEqual(
                url,
                "https://codeload.github.com/redhat-developer/"
                "rhdh-plugin-export-overlays/tar.gz/release-2.1",
            )
            self.assertTrue((dest / "default.packages.yaml").is_file())

    def test_missing_ref_is_reported_as_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "overlay_repo.urllib.request.urlopen",
                side_effect=urllib.error.HTTPError(
                    "https://example.invalid", 404, "Not Found", {}, None
                ),
            ):
                with self.assertRaises(FileNotFoundError) as ctx:
                    repo_mod.fetch_overlay_tarball("release-9.9", Path(tmp) / "overlay")
        self.assertIn("HTTP 404", str(ctx.exception))
        self.assertIn("--repo", str(ctx.exception))


class ResolveReleaseRefTests(unittest.TestCase):
    def test_existing_numbered_release_uses_its_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_overlay_git(
                Path(tmp) / "overlay", {"main": {"README.md": "main"}, "release-2.1": {}}
            )
            self.assertEqual(repo_mod.resolve_release_ref("2.1", repo=repo), ("release-2.1", False))

    def test_release_newer_than_every_branch_uses_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_overlay_git(
                Path(tmp) / "overlay",
                {
                    "main": {"README.md": "main"},
                    "release-1.9": {"README.md": "1.9"},
                    "release-2.1": {"README.md": "2.1"},
                },
            )
            with mock.patch.object(
                repo_mod, "remote_release_branches", return_value={(1, 9), (2, 1)}
            ):
                self.assertEqual(repo_mod.resolve_release_ref("2.2", repo=repo), ("main", True))

    def test_missing_older_release_does_not_fall_back_to_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_overlay_git(
                Path(tmp) / "overlay", {"main": {"README.md": "main"}, "release-2.1": {}}
            )
            with mock.patch.object(repo_mod, "remote_release_branches", return_value={(2, 1)}):
                with self.assertRaises(FileNotFoundError):
                    repo_mod.resolve_release_ref("1.8", repo=repo)

    def test_remote_release_resolution_uses_main_for_next_release(self) -> None:
        with mock.patch.object(repo_mod, "remote_release_branches", return_value={(1, 9), (2, 1)}):
            self.assertEqual(repo_mod.resolve_release_ref("2.2"), ("main", True))
            self.assertEqual(repo_mod.resolve_release_ref("2.2.0"), ("main", True))


class CollectTests(unittest.TestCase):
    def test_downloaded_ref_is_loaded_from_the_extracted_tree(self) -> None:
        def fake_fetch(ref: str, dest: Path) -> Path:
            self.assertEqual(ref, "release-1.10")
            return repo_mod.extract_overlay_tarball(
                overlay_tarball(
                    {
                        "catalog-entities/extensions/plugins/scorecard.yaml": plugin_yaml(
                            "scorecard", "Scorecard", "community"
                        )
                    }
                ),
                dest,
            )

        with (
            mock.patch.object(repo_mod, "discover_overlay_repo", return_value=None),
            mock.patch.object(repo_mod, "remote_release_branches", return_value={(1, 10)}),
            mock.patch.object(repo_mod, "fetch_overlay_tarball", side_effect=fake_fetch),
        ):
            rows, ref, source, temp_dir = repo_mod.collect_overlay(
                version="1.10",
                repo_arg=None,
                ref_arg=None,
                workdir=False,
                temp_prefix="rhdh-product-catalog-test-",
                load_workdir=lp.load_from_workdir,
                load_git=lp.load_from_git,
            )
            self.assertIsNotNone(temp_dir)
            temp_dir.cleanup()

        self.assertEqual(ref, "release-1.10")
        self.assertEqual(source["type"], "tarball")
        self.assertEqual([row["title"] for row in rows], ["Scorecard"])

    def test_next_release_uses_main_and_marks_pre_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_overlay_git(
                Path(tmp) / "overlay",
                {
                    "main": {
                        "catalog-entities/extensions/plugins/main.yaml": plugin_yaml(
                            "main", "Main Plugin", "community"
                        )
                    },
                    "release-2.1": {},
                },
            )
            with mock.patch.object(repo_mod, "remote_release_branches", return_value={(2, 1)}):
                rows, ref, source, temp_dir = repo_mod.collect_overlay(
                    version="2.2",
                    repo_arg=str(repo),
                    ref_arg=None,
                    workdir=False,
                    temp_prefix="rhdh-product-catalog-test-",
                    load_workdir=lp.load_from_workdir,
                    load_git=lp.load_from_git,
                )
                self.assertIsNone(temp_dir)
        self.assertEqual(ref, "main")
        self.assertEqual(source["pre_release"], "true")
        self.assertEqual([row["title"] for row in rows], ["Main Plugin"])

    def test_pair_downloads_each_ref_separately(self) -> None:
        def fake_fetch(ref: str, dest: Path) -> Path:
            return repo_mod.extract_overlay_tarball(
                overlay_tarball(
                    {
                        "catalog-entities/extensions/plugins/x.yaml": plugin_yaml(
                            f"{ref}-plugin", f"{ref} Plugin", "community"
                        )
                    }
                ),
                dest,
            )

        with (
            mock.patch.object(repo_mod, "discover_overlay_repo", return_value=None),
            mock.patch.object(repo_mod, "remote_release_branches", return_value={(1, 9), (1, 10)}),
            mock.patch.object(repo_mod, "fetch_overlay_tarball", side_effect=fake_fetch),
        ):
            rows_from, ref_from, rows_to, ref_to, source, temp_dir = repo_mod.collect_overlay_pair(
                version_from="1.9",
                version_to="1.10",
                repo_arg=None,
                temp_prefix="rhdh-product-catalog-test-",
                load_git=lp.load_from_git,
                load_workdir=lp.load_from_workdir,
            )
            self.assertIsNotNone(temp_dir)
            temp_dir.cleanup()

        self.assertEqual((ref_from, ref_to), ("release-1.9", "release-1.10"))
        self.assertEqual([row["title"] for row in rows_from], ["release-1.9 Plugin"])
        self.assertEqual([row["title"] for row in rows_to], ["release-1.10 Plugin"])
        self.assertEqual(source["type"], "tarball")


if __name__ == "__main__":
    unittest.main()
