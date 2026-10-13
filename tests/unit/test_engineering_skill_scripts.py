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


def test_shared_adf_parser_keeps_the_current_milestone_date():
    from datetime import datetime

    milestones = load_script(
        "skills/reference/rhdh-jira-api/scripts/adf_milestones.py",
        "rhdh_shared_adf_natural_dates",
    )
    description = {
        "type": "tableRow",
        "content": [
            {"type": "tableCell", "content": [{"type": "text", "text": "Code Freeze"}]},
            {
                "type": "tableCell",
                "content": [
                    {"type": "text", "text": "August "},
                    {"type": "text", "text": "27", "marks": [{"type": "strike"}]},
                    {"type": "text", "text": "31 (done)"},
                ],
            },
        ],
    }
    dates = milestones.extract_milestone_dates(description)
    assert dates["code_freeze"] == f"{datetime.now().year}-08-31"
    assert dates["feature_freeze"] == "TBD"
    assert milestones.parse_natural_date("Sep 2, 2025") == "2025-09-02"
    assert milestones.parse_natural_date("TBD") is None


def test_plugin_metadata_reads_every_file_at_the_requested_ref(monkeypatch):
    metadata = load_script(
        "skills/plugins/rhdh-local/scripts/fetch-plugin-metadata.py",
        "rhdh_plugin_metadata_branch",
    )
    calls = []

    def fetch_json(url):
        calls.append(url)
        return [{"name": "example-package.yaml"}]

    def fetch_yaml(url):
        calls.append(url)
        if "/catalog-entities/" in url:
            return {"metadata": {"name": "example"}, "spec": {"packages": ["example-package"]}}
        return {"spec": {"version": "1.2.3", "dynamicArtifact": "oci://example/plugin:1.2.3"}}

    monkeypatch.setattr(metadata, "_fetch_json", fetch_json)
    monkeypatch.setattr(metadata, "_fetch_yaml", fetch_yaml)
    result = metadata.fetch_plugin_metadata("example", branch="release/1.9")

    assert result["branch"] == "release/1.9"
    assert result["packages"] == [
        {
            "name": "example-package",
            "version": "1.2.3",
            "dynamicArtifact": "oci://example/plugin:1.2.3",
        }
    ]
    assert len(calls) == 3
    assert all("release%2F1.9" in url for url in calls)
    assert not any("/main/" in url for url in calls)


def test_plugin_metadata_cli_passes_branch_to_list_lookup(monkeypatch, capsys):
    metadata = load_script(
        "skills/plugins/rhdh-local/scripts/fetch-plugin-metadata.py",
        "rhdh_plugin_metadata_list_branch",
    )
    branches = []

    def list_plugins(branch="main"):
        branches.append(branch)
        return ["example"]

    monkeypatch.setattr(metadata, "list_plugins", list_plugins)
    assert metadata.main(["--list", "--branch", "v1.9.0", "--json"]) == 0
    import json

    assert json.loads(capsys.readouterr().out) == {
        "success": True,
        "branch": "v1.9.0",
        "plugins": ["example"],
    }
    assert branches == ["v1.9.0"]
