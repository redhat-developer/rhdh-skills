#!/usr/bin/env python3
"""Unit tests for candidates + workspace mapping (stdlib unittest)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "security"
    / "rhdh-plugins-cve-triager"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

from candidates import (  # noqa: E402
    SURFACE_HUB,
    is_closeable_classification,
    is_excluded_component,
    is_hub_component,
    select_candidates,
)
from git_checkout import hub_release_branch, hub_yarn_roots, release_branch  # noqa: E402
from workspace_map import infer_workspace, preferred_workspace_name  # noqa: E402
from yarn_why_paths import (  # noqa: E402
    collect_why_paths,
    package_in_yarn_lock,
    upstream_package_candidates,
)


def _issue(
    *,
    key: str,
    summary: str,
    status: str = "New",
    package: str = "vm2",
    component: str = "rhdh/red-hat-developer-hub-backstage-plugin-orchestrator-backend",
    stream: str = "rhdh-1.10",
) -> dict:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status},
            "labels": ["CVE-2026-92944", "Security"],
            "customfield_10667": "CVE-2026-92944",
            "customfield_10632": package,
            "customfield_10669": component,
            "customfield_10832": stream,
        },
    }


class CandidatesTests(unittest.TestCase):
    def test_selects_plugin_new(self) -> None:
        rows = select_candidates(
            [
                _issue(
                    key="RHIDP-17406",
                    summary="CVE-2026-92944 … orchestrator-backend [rhdh-1.10]",
                )
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["package"], "vm2")
        self.assertEqual(rows[0]["stream"], "1.10")
        self.assertEqual(rows[0]["cves"], ["CVE-2026-92944"])

    def test_selects_hub(self) -> None:
        rows = select_candidates(
            [
                _issue(
                    key="RHIDP-1",
                    summary="CVE-2026-1 hub [rhdh-1.10]",
                    component="rhdh/rhdh-hub-rhel9",
                )
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["surface"], SURFACE_HUB)
        self.assertTrue(is_hub_component("rhdh/rhdh-hub-rhel9"))
        self.assertTrue(is_hub_component("RHDH/RHDH-HUB-RHEL9"))
        self.assertFalse(is_hub_component("rhdh/rhdh-hub-rhel9-extra"))
        self.assertFalse(is_excluded_component("rhdh/rhdh-hub-rhel9"))

    def test_excludes_operator_and_must_gather(self) -> None:
        self.assertTrue(is_excluded_component("rhdh/rhdh-operator"))
        self.assertTrue(is_excluded_component("rhdh/rhdh-must-gather"))
        self.assertFalse(
            is_excluded_component("rhdh/red-hat-developer-hub-backstage-plugin-homepage")
        )
        self.assertEqual(hub_release_branch("1.10"), "release-1.10")

    def test_skips_non_new(self) -> None:
        rows = select_candidates(
            [
                _issue(
                    key="RHIDP-2",
                    summary="CVE-2026-2 x [rhdh-1.10]",
                    status="In Progress",
                )
            ]
        )
        self.assertEqual(rows, [])

    def test_closeable_exact_only(self) -> None:
        self.assertTrue(is_closeable_classification("PLUGIN_DEV"))
        self.assertTrue(is_closeable_classification("RUNNER"))
        self.assertTrue(is_closeable_classification("WORKSPACE_DEV"))
        self.assertFalse(is_closeable_classification("PLUGIN_PROD"))
        self.assertFalse(is_closeable_classification("PLUGIN_DEV+RUNNER"))
        self.assertFalse(is_closeable_classification("UNKNOWN"))


class WorkspaceMapTests(unittest.TestCase):
    def test_infers_orchestrator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspaces" / "orchestrator").mkdir(parents=True)
            (root / "workspaces" / "homepage").mkdir(parents=True)
            ws = infer_workspace(
                "rhdh/red-hat-developer-hub-backstage-plugin-orchestrator-backend",
                repo_root=root,
            )
            self.assertEqual(ws, "orchestrator")

    def test_override_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspaces" / "homepage").mkdir(parents=True)
            ws = infer_workspace(
                "rhdh/custom-thing",
                repo_root=root,
                overrides={"rhdh/custom-thing": "homepage"},
            )
            self.assertEqual(ws, "homepage")

    def test_guesses_lightspeed_without_on_disk_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspaces").mkdir()
            ws = infer_workspace(
                "rhdh/red-hat-developer-hub-backstage-plugin-lightspeed-backend",
                repo_root=root,
            )
            self.assertEqual(ws, "lightspeed")

    def test_preferred_workspace_name(self) -> None:
        self.assertEqual(
            preferred_workspace_name(
                "rhdh/red-hat-developer-hub-backstage-plugin-orchestrator-backend"
            ),
            "orchestrator",
        )


class GitCheckoutTests(unittest.TestCase):
    def test_release_branch_name(self) -> None:
        self.assertEqual(
            release_branch("1.10", "orchestrator"),
            "release-1.10/orchestrator",
        )
        self.assertEqual(
            release_branch("1.10", "lightspeed"),
            "release-1.10/lightspeed",
        )

    def test_yarn_install_missing_manifest(self) -> None:
        from git_checkout import yarn_install_workspace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspaces" / "orchestrator").mkdir(parents=True)
            result = yarn_install_workspace(root, "orchestrator")
            self.assertFalse(result["ok"])
            self.assertIn("missing", result["error"])

    def test_resolve_yarn_prefers_yarnpath(self) -> None:
        from git_checkout import resolve_yarn_command

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / ".yarn" / "releases" / "yarn-4.12.0.cjs"
            release.parent.mkdir(parents=True)
            release.write_text("// yarn\n", encoding="utf-8")
            (root / ".yarnrc.yml").write_text(
                "yarnPath: .yarn/releases/yarn-4.12.0.cjs\n",
                encoding="utf-8",
            )
            cmd = resolve_yarn_command(root)
            self.assertEqual(cmd, ["node", str(release)])

    def test_hub_cache_remembers_yarn_failure(self) -> None:
        from git_checkout import HubBranchCache

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            cache = HubBranchCache(root, yarn_install=True)
            cache._branch = "release-1.10"
            cache._yarn_errors["release-1.10"] = "yarn install failed once"
            first = cache.ensure(stream="1.10")
            second = cache.ensure(stream="1.10")
            self.assertFalse(first["ok"])
            self.assertFalse(second["ok"])
            self.assertEqual(first["error"], "yarn install failed once")
            self.assertEqual(second["error"], first["error"])

    def test_sort_candidates_groups_by_stream_workspace(self) -> None:
        from workspace_map import sort_candidates_for_checkout

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspaces" / "orchestrator").mkdir(parents=True)
            (root / "workspaces" / "homepage").mkdir(parents=True)
            rows = sort_candidates_for_checkout(
                [
                    {
                        "key": "RHIDP-3",
                        "stream": "1.10",
                        "component": ("rhdh/red-hat-developer-hub-backstage-plugin-homepage"),
                        "package": "a",
                    },
                    {
                        "key": "RHIDP-1",
                        "stream": "1.10",
                        "component": (
                            "rhdh/red-hat-developer-hub-backstage-plugin-orchestrator-backend"
                        ),
                        "package": "b",
                    },
                    {
                        "key": "RHIDP-2",
                        "stream": "1.10",
                        "component": ("rhdh/red-hat-developer-hub-backstage-plugin-orchestrator"),
                        "package": "c",
                    },
                    {
                        "key": "RHIDP-0",
                        "stream": "1.9",
                        "component": ("rhdh/red-hat-developer-hub-backstage-plugin-homepage"),
                        "package": "d",
                    },
                ],
                repo_root=root,
            )
        keys = [r["key"] for r in rows]
        # Streams sort as strings: "1.10" < "1.9"
        self.assertEqual(keys, ["RHIDP-3", "RHIDP-1", "RHIDP-2", "RHIDP-0"])
        self.assertEqual(rows[1]["workspace"], "orchestrator")
        self.assertEqual(rows[2]["workspace"], "orchestrator")


class SlackReportTests(unittest.TestCase):
    def test_readable_closed_omits_needs_triaging(self) -> None:
        from slack_report import build_payload

        payload = build_payload(
            [
                {
                    "key": "RHIDP-2",
                    "action": "would_close",
                    "reason": "PLUGIN_DEV",
                    "classification": "PLUGIN_DEV",
                    "package": "vm2",
                    "workspace": "homepage",
                },
                {
                    "key": "RHIDP-17317",
                    "action": "would_close",
                    "reason": "known_non_prod",
                    "classification": "KNOWN_NON_PROD",
                    "package": "basic-ftp",
                    "workspace": "orchestrator",
                    "allowlist": {"id": "basic-ftp-mockttp"},
                },
                {
                    "key": "RHIDP-16569",
                    "action": "left_open",
                    "classification": "PLUGIN_PROD+RUNNER",
                    "package": "dompurify",
                    "workspace": "lightspeed",
                    "stream": "1.10",
                    "cves": ["CVE-2026-92944"],
                },
                {
                    "key": "RHIDP-9",
                    "action": "left_open",
                    "classification": "PLUGIN_PROD",
                    "package": "dompurify",
                    "workspace": "lightspeed",
                    "stream": "1.9",
                    "cves": ["CVE-2026-92944"],
                },
            ],
            dry_run=True,
        )
        headers = [
            b.get("text", {}).get("text", "") for b in payload["blocks"] if b["type"] == "header"
        ]
        texts = [
            b.get("text", {}).get("text", "") for b in payload["blocks"] if b["type"] == "section"
        ]
        text = "\n".join(texts)
        self.assertIn("✅ Closed: 2", text)
        self.assertIn("📋 Needs Triaging: 2", text)
        self.assertNotIn("Needs Triaging (Prod Dependency)", "\n".join(headers))
        self.assertNotIn("Errors", text)
        self.assertIn("*✅ Closed*", text)
        self.assertIn("`vm2`", text)
        self.assertIn("(homepage | <https://redhat.atlassian.net/browse/RHIDP-2|RHIDP-2>)", text)
        self.assertIn("not used in prod path", text)
        self.assertIn("known non-prod usage (basic-ftp-mockttp)", text)
        self.assertNotIn("`dompurify`", text)
        self.assertNotIn("CVE-2026-92944", text)
        self.assertNotIn("PLUGIN_PROD", text)

    def test_left_open_prod_dependency_not_listed(self) -> None:
        from slack_report import build_payload

        payload = build_payload(
            [
                {
                    "key": "RHIDP-1",
                    "action": "left_open",
                    "surface": "hub",
                    "package": "@backstage/backend-defaults",
                    "workspace": None,
                    "stream": "1.10",
                    "branch": "release-1.10",
                    "cves": ["CVE-2026-1"],
                },
                {
                    "key": "RHIDP-2",
                    "action": "left_open",
                    "surface": "plugin",
                    "package": "dompurify",
                    "workspace": "lightspeed",
                    "stream": "1.10",
                    "branch": "release-1.10/lightspeed",
                    "cves": ["CVE-2026-2"],
                },
            ],
            dry_run=True,
        )
        text = "\n".join(b["text"]["text"] for b in payload["blocks"] if b["type"] == "section")
        headers = [
            b.get("text", {}).get("text", "") for b in payload["blocks"] if b["type"] == "header"
        ]
        self.assertIn("✅ Closed: 0 | 📋 Needs Triaging: 2", text)
        self.assertNotIn("Needs Triaging (Prod Dependency)", "\n".join(headers))
        self.assertNotIn("`dompurify`", text)
        self.assertNotIn("`@backstage/backend-defaults`", text)

    def test_closed_hub_omits_workspace_placeholder(self) -> None:
        from slack_report import build_payload

        payload = build_payload(
            [
                {
                    "key": "RHIDP-17958",
                    "action": "would_close",
                    "reason": "known_non_prod",
                    "surface": "hub",
                    "package": "nodemailer",
                    "workspace": None,
                    "allowlist": {"id": "nodemailer-notifications-email"},
                }
            ],
            dry_run=True,
        )
        text = "\n".join(b["text"]["text"] for b in payload["blocks"] if b["type"] == "section")
        self.assertIn(
            "• (<https://redhat.atlassian.net/browse/RHIDP-17958|RHIDP-17958>) `nodemailer`",
            text,
        )
        self.assertNotIn("[?]", text)
        self.assertIn("known non-prod usage (nodemailer-notifications-email)", text)

    def test_not_found_groups_package_and_same_cve(self) -> None:
        from slack_report import build_payload

        payload = build_payload(
            [
                {
                    "key": "RHIDP-17682",
                    "action": "left_open",
                    "reason": "hub_package_not_in_tree",
                    "surface": "hub",
                    "package": "@backstage/backend-defaults",
                    "workspace": None,
                    "stream": "1.10",
                    "branch": "release-1.10",
                    "cves": ["CVE-2026-10649"],
                },
                {
                    "key": "RHIDP-17719",
                    "action": "left_open",
                    "reason": "hub_package_not_in_tree",
                    "surface": "hub",
                    "package": "@backstage/backend-defaults",
                    "workspace": None,
                    "stream": "1.10",
                    "branch": "release-1.10",
                    "cves": ["CVE-2026-10649"],
                },
                {
                    "key": "RHIDP-1",
                    "action": "left_open",
                    "classification": "PLUGIN_PROD",
                    "package": "dompurify",
                    "workspace": "lightspeed",
                    "stream": "1.10",
                    "cves": ["CVE-2026-2"],
                },
            ],
            dry_run=True,
        )
        text = "\n".join(b["text"]["text"] for b in payload["blocks"] if b["type"] == "section")
        self.assertIn("`@backstage/backend-defaults`", text)
        self.assertIn(
            "• :warning: Duplicate tickets "
            "<https://access.redhat.com/security/cve/CVE-2026-10649|CVE-2026-10649>"
            "(<https://redhat.atlassian.net/browse/RHIDP-17682|RHIDP-17682>, "
            "<https://redhat.atlassian.net/browse/RHIDP-17719|RHIDP-17719>)",
            text,
        )
        self.assertNotIn("`dompurify`", text)
        self.assertIn("📋 Needs Triaging: 1", text)
        self.assertNotIn("Needs Triaging (Prod Dependency)", text)

    def test_hub_not_found_separate_section(self) -> None:
        from slack_report import build_payload

        payload = build_payload(
            [
                {
                    "key": "RHIDP-17308",
                    "action": "left_open",
                    "reason": "hub_package_not_in_tree",
                    "surface": "hub",
                    "package": "openssl",
                    "workspace": None,
                    "stream": "1.10",
                    "branch": "release-1.10",
                    "cves": ["CVE-2026-1"],
                },
                {
                    "key": "RHIDP-2",
                    "action": "left_open",
                    "surface": "hub",
                    "package": "@backstage/backend-defaults",
                    "workspace": None,
                    "stream": "1.10",
                    "branch": "release-1.10",
                    "cves": ["CVE-2026-2"],
                },
            ],
            dry_run=True,
        )
        headers = [
            b.get("text", {}).get("text", "") for b in payload["blocks"] if b["type"] == "header"
        ]
        text = "\n".join(b["text"]["text"] for b in payload["blocks"] if b["type"] == "section")
        self.assertIn("🔍 Not found", headers)
        self.assertNotIn("Needs Triaging (Prod Dependency)", "\n".join(headers))
        self.assertIn("🔍 Not found: 1", text)
        self.assertIn("📋 Needs Triaging: 1", text)
        self.assertIn("`openssl`", text)
        self.assertNotIn("`@backstage/backend-defaults`", text)

    def test_omits_errors_when_zero(self) -> None:
        from slack_report import build_payload

        payload = build_payload(
            [
                {
                    "key": "RHIDP-1",
                    "action": "left_open",
                    "classification": "PLUGIN_PROD",
                    "package": "dompurify",
                    "workspace": "lightspeed",
                    "stream": "1.10",
                    "cves": ["CVE-2026-1"],
                }
            ],
            dry_run=True,
        )
        text = "\n".join(b["text"]["text"] for b in payload["blocks"] if b["type"] == "section")
        self.assertIn("✅ Closed: 0 | 📋 Needs Triaging: 1", text)
        self.assertNotIn("Errors", text)
        self.assertNotIn("`dompurify`", text)
        self.assertNotIn("PLUGIN_PROD", text)

    def test_chunks_long_section_and_patches_many_blocks(self) -> None:
        from slack_report import _SECTION_MAX, build_payloads

        rows = [
            {
                "key": f"RHIDP-{i}",
                "action": "left_open",
                "reason": "hub_package_not_in_tree",
                "surface": "hub",
                "package": f"pkg-{i}",
                "workspace": None,
                "stream": "1.10",
                "branch": "release-1.10",
                "cves": [f"CVE-2026-{i}"],
            }
            for i in range(200)
        ]
        payloads = build_payloads(rows, dry_run=True)
        self.assertGreaterEqual(len(payloads), 1)
        for payload in payloads:
            for block in payload["blocks"]:
                if block.get("type") == "section":
                    self.assertLessEqual(len(block["text"]["text"]), _SECTION_MAX + 1)
        joined = "\n".join(
            b["text"]["text"] for p in payloads for b in p["blocks"] if b.get("type") == "section"
        )
        self.assertIn("RHIDP-0", joined)
        self.assertIn("RHIDP-199", joined)
        if len(payloads) > 1:
            self.assertIn("1/", payloads[0]["text"])


class YarnWhyPathsTests(unittest.TestCase):
    def test_collect_why_paths_for_hub(self) -> None:
        why = """
├─ @backstage/backend-defaults@workspace:packages/backend-defaults
│  └─ mockttp@npm:3.15.4
│     └─ basic-ftp@npm:5.0.5
├─ backend@workspace:packages/backend
│  └─ some-real-dep@npm:1.0.0
│     └─ basic-ftp@npm:5.0.5
""".strip()
        paths = collect_why_paths(why, "basic-ftp")
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0]["root"], "@backstage/backend-defaults")
        self.assertIn("mockttp", paths[0]["path"])
        self.assertEqual(paths[1]["root"], "backend")

    def test_upstream_package_candidates(self) -> None:
        self.assertEqual(
            upstream_package_candidates("@backstage/plugin-techdocs-node; plugin-techdocs-node"),
            [
                "@backstage/plugin-techdocs-node",
                "plugin-techdocs-node",
            ],
        )
        self.assertEqual(
            upstream_package_candidates("plugin-scaffolder-backend"),
            [
                "@backstage/plugin-scaffolder-backend",
                "plugin-scaffolder-backend",
            ],
        )

    def test_package_in_yarn_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "yarn.lock"
            lock.write_text(
                '"nodemailer@npm:^7.0.7":\n  version: 7.0.13\n',
                encoding="utf-8",
            )
            self.assertTrue(package_in_yarn_lock(lock, "nodemailer"))
            self.assertFalse(package_in_yarn_lock(lock, "openssl"))

    def test_hub_yarn_roots_includes_dynamic_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "yarn.lock").write_text("", encoding="utf-8")
            self.assertEqual(hub_yarn_roots(root), [root])
            dp = root / "dynamic-plugins"
            dp.mkdir()
            (dp / "package.json").write_text("{}", encoding="utf-8")
            (dp / "yarn.lock").write_text("", encoding="utf-8")
            self.assertEqual(hub_yarn_roots(root), [root, dp])

    def test_collect_hub_why_merges_dynamic_plugins(self) -> None:
        import yarn_why_paths as why_mod

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dp = root / "dynamic-plugins"
            dp.mkdir()
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "yarn.lock").write_text("", encoding="utf-8")
            (dp / "package.json").write_text("{}", encoding="utf-8")
            (dp / "yarn.lock").write_text(
                '"@backstage/plugin-techdocs-node@npm:^1.14.4":\n  version: 1.14.4\n',
                encoding="utf-8",
            )

            def fake_why(cwd: Path, package: str, **_kwargs):
                if cwd == dp and package == "@backstage/plugin-techdocs-node":
                    return {
                        "ok": True,
                        "output": (
                            "├─ wrapper@workspace:wrappers/techdocs\n"
                            "│  └─ @backstage/plugin-techdocs-node@npm:1.14.4\n"
                        ),
                    }
                return {
                    "ok": False,
                    "error": f"yarn why -R {package} returned no output",
                    "output": "",
                }

            original = why_mod.run_yarn_why
            why_mod.run_yarn_why = fake_why  # type: ignore[assignment]
            try:
                result = why_mod.collect_hub_why(
                    hub_yarn_roots(root),
                    "@backstage/plugin-techdocs-node; plugin-techdocs-node",
                )
            finally:
                why_mod.run_yarn_why = original

        self.assertTrue(result["ok"])
        self.assertEqual(result["package"], "@backstage/plugin-techdocs-node")
        self.assertEqual(len(result["paths"]), 1)
        self.assertEqual(result["paths"][0]["hubRoot"], "dynamic-plugins")
        self.assertIn(
            "dynamic-plugins:@backstage/plugin-techdocs-node",
            result["hits"],
        )


class AllowlistTests(unittest.TestCase):
    def test_load_shipped_allowlist(self) -> None:
        from allowlist import default_allowlist_path, load_allowlist

        entries = load_allowlist(default_allowlist_path())
        self.assertGreaterEqual(len(entries), 5)
        by_id = {e["id"]: e for e in entries}
        self.assertIn("mockttp", by_id["basic-ftp-mockttp"]["reached_via"])
        self.assertIn("mockttp", by_id["graphql-tools-utils-mockttp"]["reached_via"])
        self.assertIn("node-gyp", by_id["tar-node-gyp"]["reached_via"])
        self.assertIn(
            "webpack-dev-server",
            by_id["webpack-dev-middleware-wds"]["reached_via"],
        )
        self.assertEqual(
            by_id["nodemailer-notifications-email"]["non_ga_plugin"],
            "@backstage/plugin-notifications-backend-module-email",
        )
        self.assertEqual(by_id["infinispan-unsupported"]["package"], "*")
        self.assertIn("infinispan", by_id["infinispan-unsupported"]["reached_via"])
        self.assertEqual(by_id["via-backstage-cli"]["package"], "*")
        self.assertIn("@backstage/cli", by_id["via-backstage-cli"]["reached_via"])
        self.assertIn(
            "@backstage/backend-test-utils",
            by_id["via-backstage-backend-test-utils"]["reached_via"],
        )
        self.assertNotIn("undici-via-infinispan", by_id)
        for entry in entries:
            self.assertEqual(entry["release"], ["1.10"], entry["id"])

    def test_path_gate_and_match(self) -> None:
        from allowlist import match_allowlist, path_gate_matches

        entries = [
            {
                "id": "basic-ftp-mockttp",
                "package": "basic-ftp",
                "reached_via": ["mockttp"],
                "non_ga_plugin": None,
                "rationale": "test",
                "workspaces": None,
                "release": ["1.10"],
                "vex": None,
            }
        ]
        prod_ok = [
            {
                "plugin": "orchestrator-backend",
                "firstHop": "@backstage/plugin-scaffolder-backend",
                "path": [
                    "@red-hat-developer-hub/backstage-plugin-orchestrator-backend",
                    "@backstage/plugin-scaffolder-backend",
                    "@backstage/backend-openapi-utils",
                    "mockttp",
                    "pac-proxy-agent",
                    "basic-ftp",
                ],
            }
        ]
        prod_mixed = [
            prod_ok[0],
            {
                "plugin": "orchestrator-backend",
                "firstHop": "some-real-dep",
                "path": [
                    "@red-hat-developer-hub/backstage-plugin-orchestrator-backend",
                    "some-real-dep",
                    "basic-ftp",
                ],
            },
        ]
        self.assertTrue(path_gate_matches(prod_ok, ["mockttp"]))
        self.assertFalse(path_gate_matches(prod_ok, ["node-gyp"]))
        self.assertFalse(path_gate_matches(prod_mixed, ["mockttp"]))
        self.assertFalse(path_gate_matches([], ["mockttp"]))
        hit = match_allowlist(
            entries,
            package="basic-ftp",
            workspace="orchestrator",
            stream="1.10",
            plugin_prod_paths=prod_ok,
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["id"], "basic-ftp-mockttp")
        miss = match_allowlist(
            entries,
            package="basic-ftp",
            workspace="orchestrator",
            stream="1.10",
            plugin_prod_paths=prod_mixed,
        )
        self.assertIsNone(miss)

    def test_star_package_matches_any_leaf_via_marker(self) -> None:
        from allowlist import match_allowlist

        entries = [
            {
                "id": "infinispan-unsupported",
                "package": "*",
                "reached_via": ["infinispan"],
                "non_ga_plugin": None,
                "rationale": "unsupported cache",
                "workspaces": None,
                "release": ["1.10"],
                "vex": None,
            }
        ]
        paths = [
            {
                "path": [
                    "@red-hat-developer-hub/backstage-plugin-orchestrator-backend",
                    "@backstage/backend-defaults",
                    "infinispan",
                    "undici",
                ]
            }
        ]
        hit = match_allowlist(
            entries,
            package="undici",
            workspace="orchestrator",
            stream="1.10",
            plugin_prod_paths=paths,
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["id"], "infinispan-unsupported")
        miss = match_allowlist(
            entries,
            package="undici",
            workspace="orchestrator",
            stream="1.10",
            plugin_prod_paths=[
                {
                    "path": [
                        "@red-hat-developer-hub/backstage-plugin-orchestrator-backend",
                        "real-dep",
                        "undici",
                    ]
                }
            ],
        )
        self.assertIsNone(miss)

    def test_release_filter_matches_ticket_stream(self) -> None:
        from allowlist import _normalize_entry, match_allowlist

        entry = _normalize_entry(
            {
                "id": "via-cli-scoped",
                "package": "*",
                "reached_via": ["@backstage/cli"],
                "rationale": "cli only on 1.9/1.10",
                "release": ["1.9", "1.10"],
            },
            0,
        )
        self.assertEqual(entry["release"], ["1.9", "1.10"])
        # streams: is a load-time alias for release.
        aliased = _normalize_entry(
            {
                "id": "via-alias",
                "package": "basic-ftp",
                "reached_via": ["mockttp"],
                "rationale": "alias",
                "streams": ["1.10"],
            },
            1,
        )
        self.assertEqual(aliased["release"], ["1.10"])

        paths = [
            {
                "path": [
                    "@red-hat-developer-hub/backstage-plugin-orchestrator-backend",
                    "@backstage/cli",
                    "undici",
                ]
            }
        ]
        hit = match_allowlist(
            [entry],
            package="undici",
            workspace="orchestrator",
            stream="1.10",
            plugin_prod_paths=paths,
        )
        self.assertIsNotNone(hit)
        miss = match_allowlist(
            [entry],
            package="undici",
            workspace="orchestrator",
            stream="1.8",
            plugin_prod_paths=paths,
        )
        self.assertIsNone(miss)
        # Ticket Update Stream may arrive as rhdh-1.9.
        hit_prefixed = match_allowlist(
            [entry],
            package="undici",
            workspace="orchestrator",
            stream="rhdh-1.9",
            plugin_prod_paths=paths,
        )
        self.assertIsNotNone(hit_prefixed)

    def test_entry_without_gate_does_not_allowlist_close(self) -> None:
        from allowlist import _normalize_entry, match_allowlist

        entry = _normalize_entry(
            {
                "id": "context-only",
                "package": "basic-ftp",
                "rationale": "catalog context; no auto-close gate",
                "release": ["1.10"],
            },
            0,
        )
        self.assertEqual(entry["reached_via"], [])
        self.assertIsNone(entry["non_ga_plugin"])
        miss = match_allowlist(
            [entry],
            package="basic-ftp",
            workspace="orchestrator",
            stream="1.10",
            plugin_prod_paths=[
                {
                    "path": [
                        "@red-hat-developer-hub/backstage-plugin-orchestrator-backend",
                        "mockttp",
                        "basic-ftp",
                    ]
                }
            ],
            plugin_prod=[],
        )
        self.assertIsNone(miss)

    def test_hub_skips_entries_with_workspaces_filter(self) -> None:
        from allowlist import match_allowlist

        entry = {
            "id": "basic-ftp-mockttp",
            "package": "basic-ftp",
            "reached_via": ["mockttp"],
            "non_ga_plugin": None,
            "rationale": "plugin only",
            "workspaces": ["orchestrator"],
            "release": ["1.10"],
            "vex": None,
        }
        paths = [{"path": ["backend", "mockttp", "basic-ftp"]}]
        miss = match_allowlist(
            [entry],
            package="basic-ftp",
            workspace=None,
            stream="1.10",
            plugin_prod_paths=paths,
            plugin_prod=[{"packageName": "backend"}],
        )
        self.assertIsNone(miss)
        entry_open = {**entry, "workspaces": None}
        hit = match_allowlist(
            [entry_open],
            package="basic-ftp",
            workspace=None,
            stream="1.10",
            plugin_prod_paths=paths,
            plugin_prod=[{"packageName": "backend"}],
        )
        self.assertIsNotNone(hit)

    def test_via_contains_alias(self) -> None:
        from allowlist import _normalize_entry

        entry = _normalize_entry(
            {
                "id": "alias",
                "package": "basic-ftp",
                "rationale": "legacy key",
                "via_contains": ["mockttp"],
                "release": ["1.10"],
            },
            0,
        )
        self.assertEqual(entry["reached_via"], ["mockttp"])
        self.assertIsNone(entry["non_ga_plugin"])

    def test_release_is_required(self) -> None:
        from allowlist import _normalize_entry

        with self.assertRaises(ValueError) as ctx:
            _normalize_entry(
                {
                    "id": "missing-release",
                    "package": "basic-ftp",
                    "reached_via": ["mockttp"],
                    "rationale": "no release",
                },
                0,
            )
        self.assertIn("release is required", str(ctx.exception))

    def test_non_ga_plugin_only_entry(self) -> None:
        from allowlist import _normalize_entry, match_allowlist

        entry = _normalize_entry(
            {
                "id": "leaf-notifications-email",
                "package": "some-leaf",
                "non_ga_plugin": ("@backstage/plugin-notifications-backend-module-email"),
                "rationale": "unsupported plugin only",
                "release": ["1.10"],
            },
            0,
        )
        self.assertEqual(entry["reached_via"], [])
        self.assertEqual(
            entry["non_ga_plugin"],
            "@backstage/plugin-notifications-backend-module-email",
        )
        plugin = "@backstage/plugin-notifications-backend-module-email"
        hit = match_allowlist(
            [entry],
            package="some-leaf",
            workspace="notifications",
            stream="1.10",
            plugin_prod_paths=[
                {
                    "plugin": "notifications-backend-module-email",
                    "path": [plugin, "some-leaf"],
                }
            ],
            plugin_prod=[{"plugin": "x", "packageName": plugin}],
        )
        self.assertIsNotNone(hit)
        miss = match_allowlist(
            [entry],
            package="some-leaf",
            workspace="notifications",
            stream="1.10",
            plugin_prod_paths=[
                {"path": [plugin, "some-leaf"]},
                {
                    "path": [
                        "@red-hat-developer-hub/backstage-plugin-orchestrator-backend",
                        "some-leaf",
                    ]
                },
            ],
            plugin_prod=[
                {"packageName": plugin},
                {"packageName": ("@red-hat-developer-hub/backstage-plugin-orchestrator-backend")},
            ],
        )
        self.assertIsNone(miss)

    def test_non_ga_plugin_hub_wrapper_tree(self) -> None:
        """Hub yarn why -R roots at the dynamic-plugins wrapper workspace."""
        from allowlist import match_allowlist

        plugin = "@backstage/plugin-notifications-backend-module-email"
        wrapper = "backstage-plugin-notifications-backend-module-email"
        entry = {
            "id": "nodemailer-notifications-email",
            "package": "nodemailer",
            "reached_via": [],
            "non_ga_plugin": plugin,
            "rationale": "unsupported plugin only",
            "workspaces": None,
            "release": ["1.10"],
            "vex": None,
        }
        hit = match_allowlist(
            [entry],
            package="nodemailer",
            workspace=None,
            stream="1.10",
            plugin_prod_paths=[
                {"path": [wrapper, plugin, "nodemailer"]},
            ],
            plugin_prod=[{"packageName": wrapper}],
        )
        self.assertIsNotNone(hit)
        miss = match_allowlist(
            [entry],
            package="nodemailer",
            workspace=None,
            stream="1.10",
            plugin_prod_paths=[
                {"path": [wrapper, plugin, "nodemailer"]},
                {
                    "path": [
                        "@backstage/plugin-scaffolder-backend",
                        "nodemailer",
                    ]
                },
            ],
            plugin_prod=[
                {"packageName": wrapper},
                {"packageName": "@backstage/plugin-scaffolder-backend"},
            ],
        )
        self.assertIsNone(miss)


class TriageClassifyTests(unittest.TestCase):
    def test_hub_allowlist_close_without_classify(self) -> None:
        import triage as triage_mod

        candidate = {
            "key": "RHIDP-17467",
            "summary": "CVE-2026-1 basic-ftp hub",
            "package": "basic-ftp",
            "component": "rhdh/rhdh-hub-rhel9",
            "stream": "1.10",
            "cves": ["CVE-2026-1"],
            "surface": SURFACE_HUB,
            "workspace": None,
        }
        entries = [
            {
                "id": "basic-ftp-mockttp",
                "package": "basic-ftp",
                "reached_via": ["mockttp"],
                "non_ga_plugin": None,
                "rationale": "mockttp only",
                "workspaces": None,
                "release": ["1.10"],
                "vex": None,
            }
        ]

        class FakeHubCache:
            def ensure(self, *, stream: str):
                return {"ok": True, "branch": f"release-{stream}"}

        def fake_hub_why(roots, package, **_kwargs):
            return {
                "ok": True,
                "package": package,
                "hits": ["root:basic-ftp"],
                "paths": [
                    {
                        "root": "backend",
                        "path": ["backend", "mockttp", "basic-ftp"],
                        "hubRoot": "root",
                    }
                ],
            }

        class FakeClosure:
            def __init__(self):
                self.result = "would_close"
                self.message = "dry-run"
                self.error_detail = None

        original_why = triage_mod.collect_hub_why
        original_close = triage_mod.close_not_a_bug
        triage_mod.collect_hub_why = fake_hub_why  # type: ignore[assignment]
        triage_mod.close_not_a_bug = lambda *a, **k: FakeClosure()  # type: ignore[assignment]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                row = triage_mod.triage_one(
                    candidate,
                    creds={"host": "example", "email": "a", "token": "b"},
                    repo_root=Path(tmp),
                    map_path=None,
                    classify_script=None,
                    dry_run=True,
                    branch_cache=None,
                    allowlist_entries=entries,
                    hub_root=Path(tmp),
                    hub_cache=FakeHubCache(),  # type: ignore[arg-type]
                )
            self.assertEqual(row["action"], "would_close")
            self.assertEqual(row["reason"], "known_non_prod")
            self.assertEqual(row["classification"], "KNOWN_NON_PROD")
            self.assertEqual(row["branch"], "release-1.10")
        finally:
            triage_mod.collect_hub_why = original_why
            triage_mod.close_not_a_bug = original_close

    def test_hub_openssl_not_in_tree_needs_triage(self) -> None:
        import triage as triage_mod

        candidate = {
            "key": "RHIDP-17308",
            "summary": "CVE openssl hub",
            "package": "openssl",
            "component": "rhdh/rhdh-hub-rhel9",
            "stream": "1.10",
            "cves": ["CVE-2026-1"],
            "surface": SURFACE_HUB,
            "workspace": None,
        }

        class FakeHubCache:
            def __init__(self) -> None:
                self.ensure_calls = 0

            def ensure(self, *, stream: str):
                self.ensure_calls += 1
                return {"ok": True, "branch": f"release-{stream}"}

        cache = FakeHubCache()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "yarn.lock").write_text(
                '"nodemailer@npm:7.0.13":\n  version: 7.0.13\n',
                encoding="utf-8",
            )
            row = triage_mod.triage_one(
                candidate,
                creds={"host": "example", "email": "a", "token": "b"},
                repo_root=root,
                map_path=None,
                classify_script=None,
                dry_run=True,
                branch_cache=None,
                hub_root=root,
                hub_cache=cache,  # type: ignore[arg-type]
            )
        self.assertEqual(row["action"], "left_open")
        self.assertEqual(row["reason"], "hub_package_not_in_tree")
        self.assertEqual(row["classification"], "HUB")
        self.assertEqual(cache.ensure_calls, 1)

    def test_retries_backstage_scoped_package_name(self) -> None:
        import triage as triage_mod

        candidate = {
            "key": "RHIDP-17741",
            "summary": "CVE plugin-scaffolder-backend",
            "package": "plugin-scaffolder-backend",
            "component": ("rhdh/red-hat-developer-hub-backstage-plugin-orchestrator-backend"),
            "stream": "1.10",
            "cves": ["CVE-2026-1"],
        }
        tried: list[str] = []

        def fake_resolve(component, **_kwargs):
            return {"workspace": "orchestrator"}

        def fake_classify(*, package, **_kwargs):
            tried.append(package)
            if package == "plugin-scaffolder-backend":
                return {
                    "ok": False,
                    "error": (
                        "Error: yarn why -R plugin-scaffolder-backend failed: "
                        "yarn why returned no output; run `yarn install` "
                        "in the workspace first"
                    ),
                }
            return {
                "ok": True,
                "classification": "PLUGIN_PROD",
                "customerImpact": True,
                "pluginProdPaths": [],
                "pluginProd": [],
            }

        original_resolve = triage_mod.resolve_workspace
        original_classify = triage_mod.classify_package
        triage_mod.resolve_workspace = fake_resolve  # type: ignore[assignment]
        triage_mod.classify_package = fake_classify  # type: ignore[assignment]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                row = triage_mod.triage_one(
                    candidate,
                    creds={"host": "example", "email": "a", "token": "b"},
                    repo_root=Path(tmp),
                    map_path=None,
                    classify_script=None,
                    dry_run=True,
                    branch_cache=None,
                )
            self.assertEqual(
                tried,
                [
                    "@backstage/plugin-scaffolder-backend",
                    # first candidate succeeds — bare name not tried
                ],
            )
            self.assertEqual(row["action"], "left_open")
            self.assertEqual(row["package"], "@backstage/plugin-scaffolder-backend")
        finally:
            triage_mod.resolve_workspace = original_resolve
            triage_mod.classify_package = original_classify

    def test_closes_exact_non_prod(self) -> None:
        import triage as triage_mod

        candidate = {
            "key": "RHIDP-17465",
            "summary": "CVE-2025-1 vm2",
            "package": "vm2",
            "component": "rhdh/red-hat-developer-hub-backstage-plugin-homepage",
            "stream": "1.10",
            "cves": ["CVE-2025-1"],
        }

        def fake_resolve(component, **_kwargs):
            return {"workspace": "homepage"}

        def fake_classify(**_kwargs):
            return {
                "ok": True,
                "classification": "PLUGIN_DEV",
                "customerImpact": False,
            }

        class FakeClosure:
            def __init__(self, result="would_close", message="dry-run"):
                self.result = result
                self.message = message
                self.error_detail = None

        original_resolve = triage_mod.resolve_workspace
        original_classify = triage_mod.classify_package
        original_close = triage_mod.close_not_a_bug
        triage_mod.resolve_workspace = fake_resolve  # type: ignore[assignment]
        triage_mod.classify_package = fake_classify  # type: ignore[assignment]
        triage_mod.close_not_a_bug = lambda *a, **k: FakeClosure()  # type: ignore[assignment]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                row = triage_mod.triage_one(
                    candidate,
                    creds={"host": "example", "email": "a", "token": "b"},
                    repo_root=Path(tmp),
                    map_path=None,
                    classify_script=None,
                    dry_run=True,
                    branch_cache=None,
                )
            self.assertEqual(row["action"], "would_close")
            self.assertEqual(row["reason"], "PLUGIN_DEV")
            self.assertEqual(row["classification"], "PLUGIN_DEV")
        finally:
            triage_mod.resolve_workspace = original_resolve
            triage_mod.classify_package = original_classify
            triage_mod.close_not_a_bug = original_close

    def test_leaves_prod_open(self) -> None:
        import triage as triage_mod

        candidate = {
            "key": "RHIDP-9",
            "summary": "CVE-2025-2 vm2",
            "package": "vm2",
            "component": "rhdh/red-hat-developer-hub-backstage-plugin-homepage",
            "stream": "1.10",
            "cves": ["CVE-2025-2"],
        }

        def fake_resolve(component, **_kwargs):
            return {"workspace": "homepage"}

        def fake_classify(**_kwargs):
            return {
                "ok": True,
                "classification": "PLUGIN_PROD",
                "customerImpact": True,
            }

        original_resolve = triage_mod.resolve_workspace
        original_classify = triage_mod.classify_package
        triage_mod.resolve_workspace = fake_resolve  # type: ignore[assignment]
        triage_mod.classify_package = fake_classify  # type: ignore[assignment]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                row = triage_mod.triage_one(
                    candidate,
                    creds={"host": "example", "email": "a", "token": "b"},
                    repo_root=Path(tmp),
                    map_path=None,
                    classify_script=None,
                    dry_run=True,
                    branch_cache=None,
                )
            self.assertEqual(row["action"], "left_open")
            self.assertEqual(row["classification"], "PLUGIN_PROD")
        finally:
            triage_mod.resolve_workspace = original_resolve
            triage_mod.classify_package = original_classify

    def test_closes_allowlist_when_path_gate_matches(self) -> None:
        import triage as triage_mod

        candidate = {
            "key": "RHIDP-17317",
            "summary": "CVE-2026-1 basic-ftp",
            "package": "basic-ftp",
            "component": ("rhdh/red-hat-developer-hub-backstage-plugin-orchestrator-backend"),
            "stream": "1.10",
            "cves": ["CVE-2026-1"],
        }
        entries = [
            {
                "id": "basic-ftp-mockttp",
                "package": "basic-ftp",
                "reached_via": ["mockttp"],
                "non_ga_plugin": None,
                "rationale": "mockttp only",
                "workspaces": None,
                "release": ["1.10"],
                "vex": None,
            }
        ]

        def fake_resolve(component, **_kwargs):
            return {"workspace": "orchestrator"}

        def fake_classify(**_kwargs):
            return {
                "ok": True,
                "classification": "PLUGIN_PROD+PLUGIN_DEV",
                "customerImpact": "high",
                "pluginProd": [],
                "pluginProdPaths": [
                    {
                        "plugin": "orchestrator-backend",
                        "firstHop": "@backstage/plugin-scaffolder-backend",
                        "path": [
                            ("@red-hat-developer-hub/backstage-plugin-orchestrator-backend"),
                            "@backstage/plugin-scaffolder-backend",
                            "@backstage/backend-openapi-utils",
                            "mockttp",
                            "pac-proxy-agent",
                            "basic-ftp",
                        ],
                    }
                ],
            }

        class FakeClosure:
            def __init__(self, result="would_close", message="dry-run"):
                self.result = result
                self.message = message
                self.error_detail = None

        original_resolve = triage_mod.resolve_workspace
        original_classify = triage_mod.classify_package
        original_close = triage_mod.close_not_a_bug
        triage_mod.resolve_workspace = fake_resolve  # type: ignore[assignment]
        triage_mod.classify_package = fake_classify  # type: ignore[assignment]
        triage_mod.close_not_a_bug = lambda *a, **k: FakeClosure()  # type: ignore[assignment]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                row = triage_mod.triage_one(
                    candidate,
                    creds={"host": "example", "email": "a", "token": "b"},
                    repo_root=Path(tmp),
                    map_path=None,
                    classify_script=None,
                    dry_run=True,
                    branch_cache=None,
                    allowlist_entries=entries,
                )
            self.assertEqual(row["action"], "would_close")
            self.assertEqual(row["reason"], "known_non_prod")
            self.assertEqual(row["classification"], "KNOWN_NON_PROD")
            self.assertEqual(row["allowlist"]["id"], "basic-ftp-mockttp")
        finally:
            triage_mod.resolve_workspace = original_resolve
            triage_mod.classify_package = original_classify
            triage_mod.close_not_a_bug = original_close

    def test_allowlist_miss_leaves_open(self) -> None:
        import triage as triage_mod

        candidate = {
            "key": "RHIDP-1",
            "summary": "CVE-2026-1 basic-ftp",
            "package": "basic-ftp",
            "component": ("rhdh/red-hat-developer-hub-backstage-plugin-orchestrator-backend"),
            "stream": "1.10",
            "cves": ["CVE-2026-1"],
        }
        entries = [
            {
                "id": "basic-ftp-mockttp",
                "package": "basic-ftp",
                "reached_via": ["mockttp"],
                "non_ga_plugin": None,
                "rationale": "mockttp only",
                "workspaces": None,
                "release": ["1.10"],
                "vex": None,
            }
        ]

        def fake_resolve(component, **_kwargs):
            return {"workspace": "orchestrator"}

        def fake_classify(**_kwargs):
            return {
                "ok": True,
                "classification": "PLUGIN_PROD",
                "customerImpact": "high",
                "pluginProd": [],
                "pluginProdPaths": [
                    {
                        "plugin": "orchestrator-backend",
                        "firstHop": "openapi-generator-cli",
                        "path": [
                            "orchestrator-backend",
                            "openapi-generator-cli",
                            "basic-ftp",
                        ],
                    }
                ],
            }

        original_resolve = triage_mod.resolve_workspace
        original_classify = triage_mod.classify_package
        triage_mod.resolve_workspace = fake_resolve  # type: ignore[assignment]
        triage_mod.classify_package = fake_classify  # type: ignore[assignment]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                row = triage_mod.triage_one(
                    candidate,
                    creds={"host": "example", "email": "a", "token": "b"},
                    repo_root=Path(tmp),
                    map_path=None,
                    classify_script=None,
                    dry_run=True,
                    branch_cache=None,
                    allowlist_entries=entries,
                )
            self.assertEqual(row["action"], "left_open")
            self.assertEqual(row["classification"], "PLUGIN_PROD")
        finally:
            triage_mod.resolve_workspace = original_resolve
            triage_mod.classify_package = original_classify


if __name__ == "__main__":
    unittest.main()
