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


def test_overlay_triage_names_the_next_command_from_pr_state():
    triage = load_script(
        "skills/plugins/rhdh-overlay/scripts/triage-prs.py",
        "rhdh_overlay_triage_prs_state",
    )

    def pr(**overrides):
        base = {
            "labels": [],
            "files": [{"path": "workspaces/catalog/source.json"}],
            "statusCheckRollup": [],
        }
        base.update(overrides)
        return base

    def check(name, conclusion, completed_at="2026-01-01T00:00:00Z"):
        return {"name": name, "conclusion": conclusion, "completedAt": completed_at}

    def status(context, state, started_at="2026-01-01T00:00:00Z"):
        # `publish` and `smoketest` arrive as StatusContext, not CheckRun.
        return {
            "__typename": "StatusContext",
            "context": context,
            "state": state,
            "startedAt": started_at,
        }

    assert triage.evaluate_pr_state(pr())[0] == "publish-missing"
    assert (
        triage.evaluate_pr_state(pr(statusCheckRollup=[status("publish", "SUCCESS")]))[0] == "ready"
    )
    assert triage.evaluate_pr_state(pr(statusCheckRollup=[status("publish", "FAILURE")]))[0] == (
        "publish-failed"
    )
    assert triage.evaluate_pr_state(pr(isDraft=True))[0] == "draft"
    assert triage.evaluate_pr_state(pr(labels=[{"name": "do-not-merge"}]))[0] == "skip"

    rerun = [status("publish", "FAILURE"), status("publish", "SUCCESS", "2026-01-02T00:00:00Z")]
    assert triage.evaluate_pr_state(pr(statusCheckRollup=rerun))[0] == "ready"

    pending_rerun = [
        status("publish", "SUCCESS"),
        status("publish", "PENDING", "2026-01-02T00:00:00Z"),
    ]
    assert triage.evaluate_pr_state(pr(statusCheckRollup=pending_rerun))[0] == "publish-pending"

    cancelled = [status("publish", "CANCELLED")]
    assert triage.evaluate_pr_state(pr(statusCheckRollup=cancelled))[0] == "publish-missing"

    # A CheckRun rerun keeps the newest completed run.
    checkruns = [check("publish", "FAILURE"), check("publish", "SUCCESS", "2026-01-02T00:00:00Z")]
    assert triage.evaluate_pr_state(pr(statusCheckRollup=checkruns))[0] == "ready"

    multi = [
        {"path": "workspaces/catalog/source.json"},
        {"path": "workspaces/theme/source.json"},
    ]
    state, workspaces = triage.evaluate_pr_state(
        pr(files=multi, statusCheckRollup=[status("publish", "SUCCESS")])
    )
    assert state == "ready"
    assert workspaces == ["catalog", "theme"]
    # Without the status the PR still needs the command that records it.
    assert triage.evaluate_pr_state(pr(files=multi))[0] == "publish-missing"

    # A failing check is reported even when the PR spans several workspaces.
    failing = [status("publish", "SUCCESS"), check("workspace-tests", "FAILURE")]
    assert (
        triage.evaluate_pr_state(pr(files=multi, statusCheckRollup=failing))[0] == "checks-failed"
    )


def test_overlay_triage_explains_cancelled_workspace_commands():
    triage = load_script(
        "skills/plugins/rhdh-overlay/scripts/triage-prs.py",
        "rhdh_overlay_triage_prs_scope",
    )

    assert triage.scope_note(["catalog"]) == ""
    assert "no workspace files" in triage.scope_note([])
    assert "2 workspaces" in triage.scope_note(["catalog", "theme"])
    assert "required check" in triage.scope_note(["catalog", "theme"])

    info = {
        "priority_key": "critical",
        "assignee_icon": "❌",
        "days_stale": 1,
        "state": "publish-missing",
        "next_action": triage.NEXT_ACTION["publish-missing"],
        "scope_note": triage.scope_note(["catalog", "theme"]),
    }
    assert triage.describe_next(info).startswith("Trigger /publish (2 workspaces")
    assert triage.suggest_action(info).endswith(" + Assign owner")
    assert triage.needs_action(info)

    waiting = {
        "priority_key": "critical",
        "assignee_icon": "✅",
        "days_stale": 1,
        "state": "ready",
        "next_action": triage.NEXT_ACTION["ready"],
        "scope_note": "",
    }
    assert triage.suggest_action(waiting) == "Ready to merge"
    assert not triage.needs_action(waiting)


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
