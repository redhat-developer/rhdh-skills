from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[2]


def load_script(relative_path: str, module_name: str):
    script_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fetch_pr_context_parses_supported_references_and_issue_links():
    fetch = load_script(
        "skills/plugins/rhdh-pr-review/scripts/fetch_pr_context.py",
        "rhdh_pr_review_fetch_context",
    )

    assert fetch.parse_pr_input("https://github.com/acme/widgets/pull/42") == (
        "acme/widgets",
        42,
    )
    assert fetch.parse_pr_input("acme/widgets#42") == ("acme/widgets", 42)
    assert fetch.parse_pr_input("42") == (None, 42)

    github_issues, jira_keys = fetch.extract_issue_refs(
        "Fixes #7, refs #8, and tracks RHIDP-123 plus RHIDP-123."
    )
    assert github_issues == [7, 8]
    assert jira_keys == ["RHIDP-123"]


def test_list_bot_prs_classify_branch():
    mod = load_script(
        "skills/plugins/rhdh-pr-triage/scripts/list_bot_prs.py",
        "list_bot_prs",
    )
    assert mod.classify_branch("main") == "main"
    assert mod.classify_branch("master") == "main"
    assert mod.classify_branch("release-1.10") == "release"
    assert mod.classify_branch("release-2.1") == "release"
    assert mod.classify_branch("feature-branch") == "other"


def test_list_bot_prs_normalize_dep_name():
    mod = load_script(
        "skills/plugins/rhdh-pr-triage/scripts/list_bot_prs.py",
        "list_bot_prs",
    )
    assert mod.normalize_dep_name("module google.golang.org/grpc") == "google.golang.org/grpc"
    assert mod.normalize_dep_name("digest github.com/foo/bar") == "github.com/foo/bar"
    assert mod.normalize_dep_name("google.golang.org/grpc") == "google.golang.org/grpc"

    # extract_dep_name should normalize both Renovate and Dependabot title formats
    renovate = "chore(deps): update module google.golang.org/grpc to v1.83.1"
    dependabot = "Bump google.golang.org/grpc from 1.82.1 to 1.83.1"
    assert mod.extract_dep_name(renovate) == mod.extract_dep_name(dependabot)


def test_list_bot_prs_detect_semver_level():
    mod = load_script(
        "skills/plugins/rhdh-pr-triage/scripts/list_bot_prs.py",
        "list_bot_prs",
    )
    assert mod.detect_semver_level("Bump foo from 1.2.3 to 2.0.0") == "major"
    assert mod.detect_semver_level("Update bar from 1.2.3 to 1.3.0") == "minor"
    assert mod.detect_semver_level("chore(deps): update baz 1.2.3 to 1.2.4") == "patch"
    assert mod.detect_semver_level("Update something") == "unknown"


def test_list_bot_prs_detect_go_directives():
    mod = load_script(
        "skills/plugins/rhdh-pr-triage/scripts/list_bot_prs.py",
        "list_bot_prs",
    )

    diff_go = """\
--- a/go.mod
+++ b/go.mod
-go 1.22
+go 1.23
"""
    go_bumped, tc_bumped = mod.detect_go_directives(diff_go)
    assert go_bumped
    assert not tc_bumped

    diff_tc = """\
--- a/go.mod
+++ b/go.mod
-toolchain go1.22.5
+toolchain go1.23.0
"""
    go_bumped, tc_bumped = mod.detect_go_directives(diff_tc)
    assert not go_bumped
    assert tc_bumped

    diff_neither = """\
--- a/go.mod
+++ b/go.mod
-require golang.org/x/text v0.14.0
+require golang.org/x/text v0.15.0
"""
    go_bumped, tc_bumped = mod.detect_go_directives(diff_neither)
    assert not go_bumped
    assert not tc_bumped


def test_list_bot_prs_detect_duplicates():
    mod = load_script(
        "skills/plugins/rhdh-pr-triage/scripts/list_bot_prs.py",
        "list_bot_prs",
    )

    prs = [
        {
            "repo": "redhat-developer/rhdh-operator",
            "number": 10,
            "base_branch": "main",
            "dep_name": "golang.org/x/text",
            "author": "renovate[bot]",
            "duplicate_of": None,
        },
        {
            "repo": "redhat-developer/rhdh-operator",
            "number": 11,
            "base_branch": "main",
            "dep_name": "golang.org/x/text",
            "author": "dependabot[bot]",
            "duplicate_of": None,
        },
    ]
    mod.find_duplicates(prs)
    assert prs[0]["duplicate_of"] is None
    assert prs[1]["duplicate_of"] == 10


def test_list_bot_prs_compute_ci_status():
    mod = load_script(
        "skills/plugins/rhdh-pr-triage/scripts/list_bot_prs.py",
        "list_bot_prs",
    )

    assert mod.compute_ci_status([]) == "unknown"
    assert (
        mod.compute_ci_status(
            [
                {"name": "build", "state": "SUCCESS"},
                {"name": "tide", "state": "PENDING"},
            ]
        )
        == "pass"
    )
    assert (
        mod.compute_ci_status(
            [
                {"name": "build", "state": "FAILURE"},
                {"name": "tide", "state": "PENDING"},
            ]
        )
        == "fail"
    )
    assert (
        mod.compute_ci_status(
            [
                {"name": "build", "state": "PENDING"},
            ]
        )
        == "pending"
    )


def test_list_bot_prs_detect_chart_folders():
    mod = load_script(
        "skills/plugins/rhdh-pr-triage/scripts/list_bot_prs.py",
        "list_bot_prs",
    )

    files = [
        {"path": "charts/backstage/Chart.yaml"},
        {"path": "charts/backstage/Chart.lock"},
        {"path": "charts/rhdh/Chart.yaml"},
        {"path": "README.md"},
    ]
    assert mod.detect_chart_folders(files) == ["backstage", "rhdh"]
    assert mod.detect_chart_folders([{"path": "go.mod"}]) == []


def test_list_bot_prs_detect_dep_type():
    mod = load_script(
        "skills/plugins/rhdh-pr-triage/scripts/list_bot_prs.py",
        "list_bot_prs",
    )

    assert mod.detect_dep_type("Update go.mod deps", [{"path": "go.mod"}]) == "go-module"
    assert (
        mod.detect_dep_type(
            "Bump actions/checkout from 3 to 4",
            [{"path": ".github/workflows/ci.yaml"}],
        )
        == "gh-actions"
    )
    assert (
        mod.detect_dep_type(
            "Update chart dep",
            [{"path": "charts/backstage/Chart.yaml"}],
        )
        == "chart-dep"
    )
    assert mod.detect_dep_type("Update npm package", [{"path": "package.json"}]) == "other"


def test_overlay_analyzers_preserve_workspace_and_priority_classification():
    analyze = load_script(
        "skills/plugins/rhdh-overlay/scripts/analyze-pr.py",
        "rhdh_overlay_analyze_pr",
    )
    triage = load_script(
        "skills/plugins/rhdh-overlay/scripts/triage-prs.py",
        "rhdh_overlay_triage_prs",
    )

    files = [
        {"path": "workspaces/catalog/source.json"},
        {"path": "workspaces/catalog/plugins-list.yaml"},
        {"path": "CODEOWNERS"},
    ]
    assert analyze.extract_workspaces(files) == ["catalog"]
    assert analyze.check_codeowners_modified(files)

    labels = [{"name": "mandatory-workspace"}, {"name": "workspace-update"}]
    assert analyze.classify_priority(labels)[0] == "critical"
    assert triage.classify_priority(labels)[0] == "critical"
    assert triage.extract_workspace_from_title("Update catalog workspace to 1.2.3") == "catalog"
