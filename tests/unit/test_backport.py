"""Unit tests for skills/backport/scripts/backport.py."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BACKPORT_SCRIPTS = PROJECT_ROOT / "skills" / "plugins" / "rhdh-backport" / "scripts"
if str(_BACKPORT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_BACKPORT_SCRIPTS))

import backport  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**kwargs) -> backport.BackportState:
    defaults = dict(
        release="1.10",
        pr_num=3456,
        plugin="orchestrator",
        release_branch="release-1.10/orchestrator",
        backport_branch="backport/3456-to-release-1.10",
        overlays_branch="release-1.10",
        repo="redhat-developer/rhdh-plugins",
        overlays_repo="redhat-developer/rhdh-plugin-export-overlays",
    )
    defaults.update(kwargs)
    return backport.BackportState(**defaults)


def _completed_process(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# Release version / branch model
# ---------------------------------------------------------------------------


class TestReleaseVersionHelpers:
    def test_uses_unified_from_2_1(self):
        assert backport.uses_unified_release_branch("2.1") is True
        assert backport.uses_unified_release_branch("2.2") is True

    def test_per_plugin_before_2_1(self):
        assert backport.uses_unified_release_branch("1.10") is False
        assert backport.uses_unified_release_branch("1.9") is False
        assert backport.uses_unified_release_branch("2.0") is False

    def test_release_branch_for_unified(self):
        assert backport.release_branch_for("2.1", "lightspeed") == "release-2.1"

    def test_release_branch_for_per_plugin(self):
        assert backport.release_branch_for("1.10", "lightspeed") == "release-1.10/lightspeed"

    def test_vp_changeset_branch_per_plugin(self):
        assert (
            backport.vp_changeset_branch_name(
                unified_release=False,
                plugin="orchestrator",
                release_branch="release-1.10/orchestrator",
            )
            == "maintenance-changesets-release/release-1.10/orchestrator"
        )

    def test_vp_changeset_branch_unified_per_workspace(self):
        assert (
            backport.vp_changeset_branch_name(
                unified_release=True,
                plugin="lightspeed",
                release_branch="release-2.1",
            )
            == "maintenance-changesets-release/release-2.1/lightspeed"
        )


class TestUnifiedReleaseBranchDetection:
    def test_unified_branch_naming(self):
        state = backport.BackportState(
            release="2.1",
            pr_num=4000,
            files=["workspaces/lightspeed/plugins/lightspeed/src/index.ts"],
        )
        with patch.object(backport, "run_git") as mock_git:
            mock_git.return_value = _completed_process(stdout="abc123 refs/heads/release-2.1")
            backport.step2_detect_plugin(state)

        assert state.unified_release is True
        assert state.release_branch == "release-2.1"
        assert state.plugin == "lightspeed"
        assert state.overlays_branch == "release-2.1"

    def test_unified_branch_missing_errors(self):
        state = backport.BackportState(
            release="2.1",
            pr_num=4000,
            files=["workspaces/lightspeed/plugins/lightspeed/src/index.ts"],
        )
        with patch.object(backport, "run_git") as mock_git:
            mock_git.return_value = _completed_process(stdout="")
            with pytest.raises(SystemExit):
                backport.step2_detect_plugin(state)


# ---------------------------------------------------------------------------
# Yarn.lock-only detection in step2
# ---------------------------------------------------------------------------


class TestYarnLockOnlyDetection:
    def test_yarn_lock_only_sets_flag(self):
        state = _make_state(
            files=[
                "workspaces/orchestrator/yarn.lock",
                "workspaces/orchestrator/plugins/orchestrator/yarn.lock",
            ],
        )
        with patch.object(backport, "run_git") as mock_git:
            mock_git.return_value = _completed_process(
                stdout="abc123 refs/heads/release-1.10/orchestrator"
            )
            backport.step2_detect_plugin(state)

        assert state.yarn_lock_only is True

    def test_mixed_files_no_flag(self):
        state = _make_state(
            files=[
                "workspaces/orchestrator/yarn.lock",
                "workspaces/orchestrator/plugins/orchestrator/src/index.ts",
            ],
        )
        with patch.object(backport, "run_git") as mock_git:
            mock_git.return_value = _completed_process(
                stdout="abc123 refs/heads/release-1.10/orchestrator"
            )
            backport.step2_detect_plugin(state)

        assert state.yarn_lock_only is False

    def test_no_yarn_lock_no_flag(self):
        state = _make_state(
            files=[
                "workspaces/orchestrator/plugins/orchestrator/src/index.ts",
            ],
        )
        with patch.object(backport, "run_git") as mock_git:
            mock_git.return_value = _completed_process(
                stdout="abc123 refs/heads/release-1.10/orchestrator"
            )
            backport.step2_detect_plugin(state)

        assert state.yarn_lock_only is False


# ---------------------------------------------------------------------------
# Step 7 — VP skip for yarn.lock-only
# ---------------------------------------------------------------------------


class TestStep7YarnLockOnlySkip:
    def test_skips_vp_when_yarn_lock_only(self):
        state = _make_state(yarn_lock_only=True)

        with patch.object(backport, "run_git") as mock_git:
            mock_git.return_value = _completed_process(stdout="abc123def456")
            backport.step7_detect_version_packages(state)

        assert state.vp_commit == "abc123def456"
        assert state.vp_version == "n/a (yarn.lock-only)"
        assert state.vp_pr_num == 0

    def test_calls_cleanup_when_not_yarn_lock_only(self):
        state = _make_state(yarn_lock_only=False)

        with (
            patch.object(backport, "cleanup_stale_vp_branch") as mock_cleanup,
            patch.object(backport, "run_gh_json") as mock_gh_json,
            patch.object(backport, "poll_for_vp_creation", return_value=100),
            patch.object(backport, "poll_ci"),
            patch.object(backport, "merge_pr"),
            patch.object(backport, "wait_for_merged"),
            patch("time.sleep"),
        ):
            mock_gh_json.side_effect = [
                None,
                {
                    "title": "Version Packages (orchestrator)",
                    "baseRefName": "release-1.10/orchestrator",
                },
                {
                    "mergeCommit": {"oid": "deadbeef"},
                    "body": "@redhat-developer/orchestrator@5.7.15",
                },
            ]
            backport.step7_detect_version_packages(state)

        mock_cleanup.assert_called_once_with(state)


# ---------------------------------------------------------------------------
# Step 9 — Changelog skip for yarn.lock-only
# ---------------------------------------------------------------------------


class TestStep9YarnLockOnlySkip:
    def test_skips_changelog_when_yarn_lock_only(self):
        state = _make_state(yarn_lock_only=True)

        with patch.object(backport, "run_git") as mock_git:
            backport.step9_changelog_pr(state)

        mock_git.assert_not_called()
        assert state.changelog_pr_num == 0


# ---------------------------------------------------------------------------
# Version Packages workflow bootstrap (#4173)
# ---------------------------------------------------------------------------


class TestVpWorkflowSupport:
    def test_supports_when_all_markers_present(self):
        content = """
        branches: ['workspace/**', 'release-*/*']
        version_branch_id: ${{ steps.extract.outputs.version_branch_id }}
        versionBranch: maintenance-changesets-release/${{ version_branch_id }}
        """
        assert backport.vp_workflow_supports_release_branches(content) is True

    def test_missing_release_branch_trigger(self):
        content = """
        branches: ['workspace/**']
        version_branch_id: foo
        maintenance-changesets-release/${{ version_branch_id }}
        """
        assert backport.vp_workflow_supports_release_branches(content) is False


class TestEnsureVpWorkflow:
    def test_skips_when_yarn_lock_only(self):
        state = _make_state(yarn_lock_only=True)

        with patch.object(backport, "fetch_release_branch_workflow") as mock_fetch:
            backport.ensure_vp_workflow(state)

        mock_fetch.assert_not_called()
        assert state.vp_workflow_bootstrapped is False

    def test_skips_when_unified_release(self):
        state = _make_state(
            release="2.1",
            unified_release=True,
            release_branch="release-2.1",
        )

        with patch.object(backport, "fetch_release_branch_workflow") as mock_fetch:
            backport.ensure_vp_workflow(state)

        mock_fetch.assert_not_called()
        assert state.vp_workflow_bootstrapped is False

    def test_skips_bootstrap_when_workflow_already_present(self):
        state = _make_state()
        workflow = "\n".join(backport.VP_WORKFLOW_MARKERS)

        with (
            patch.object(backport, "fetch_release_branch_workflow", return_value=workflow),
            patch.object(backport, "run_git") as mock_git,
        ):
            backport.ensure_vp_workflow(state)

        mock_git.assert_not_called()
        assert state.vp_workflow_bootstrapped is False

    def test_bootstraps_when_workflow_missing(self):
        state = _make_state()

        with (
            patch.object(backport, "fetch_release_branch_workflow", return_value="old workflow"),
            patch.object(backport, "run_git") as mock_git,
        ):
            mock_git.side_effect = [
                _completed_process(),
                _completed_process(),
                _completed_process(returncode=0),
                _completed_process(),
            ]
            backport.ensure_vp_workflow(state)

        push_calls = [
            call for call in mock_git.call_args_list if call[0][0][:2] == ["push", "upstream"]
        ]
        assert push_calls
        assert state.vp_workflow_bootstrapped is True


# ---------------------------------------------------------------------------
# Stale maintenance-changesets-release branch cleanup
# ---------------------------------------------------------------------------


class TestCleanupStaleVpBranch:
    def test_deletes_stale_branch_per_plugin(self):
        state = _make_state()

        with (
            patch.object(backport, "run_git") as mock_git,
            patch.object(backport, "run_gh") as mock_gh,
        ):
            mock_git.return_value = _completed_process(
                stdout="abc123 refs/heads/maintenance-changesets-release/release-1.10/orchestrator"
            )
            backport.cleanup_stale_vp_branch(state)

        mock_gh.assert_called_once()
        api_call = mock_gh.call_args
        assert "DELETE" in api_call[0][0]
        assert "maintenance-changesets-release/release-1.10/orchestrator" in api_call[0][0][-1]

    def test_deletes_stale_branch_unified_per_workspace(self):
        state = _make_state(
            release="2.1",
            plugin="lightspeed",
            unified_release=True,
            release_branch="release-2.1",
        )

        with (
            patch.object(backport, "run_git") as mock_git,
            patch.object(backport, "run_gh") as mock_gh,
        ):
            mock_git.return_value = _completed_process(
                stdout=("abc123 refs/heads/maintenance-changesets-release/release-2.1/lightspeed")
            )
            backport.cleanup_stale_vp_branch(state)

        api_call = mock_gh.call_args
        assert "maintenance-changesets-release/release-2.1/lightspeed" in api_call[0][0][-1]

    def test_no_delete_when_branch_missing(self):
        state = _make_state()

        with (
            patch.object(backport, "run_git") as mock_git,
            patch.object(backport, "run_gh") as mock_gh,
        ):
            mock_git.return_value = _completed_process(stdout="")
            backport.cleanup_stale_vp_branch(state)

        mock_gh.assert_not_called()


# ---------------------------------------------------------------------------
# State serialization — yarn_lock_only roundtrip
# ---------------------------------------------------------------------------


class TestStateSerialization:
    def test_yarn_lock_only_persists(self, tmp_path):
        state = _make_state(yarn_lock_only=True)
        path = tmp_path / "state.json"
        state.save(path)

        loaded = backport.BackportState.load(path)
        assert loaded.yarn_lock_only is True

    def test_yarn_lock_only_defaults_false(self, tmp_path):
        state = _make_state()
        path = tmp_path / "state.json"
        state.save(path)

        loaded = backport.BackportState.load(path)
        assert loaded.yarn_lock_only is False

    def test_unified_release_persists(self, tmp_path):
        state = _make_state(
            release="2.1",
            unified_release=True,
            release_branch="release-2.1",
        )
        path = tmp_path / "state.json"
        state.save(path)

        loaded = backport.BackportState.load(path)
        assert loaded.unified_release is True
        assert loaded.release_branch == "release-2.1"


# ---------------------------------------------------------------------------
# PR source parsing (existing logic, basic coverage)
# ---------------------------------------------------------------------------


class TestParsePrSource:
    def test_number(self):
        assert backport.parse_pr_source("3456") == (3456, None)

    def test_hash_number(self):
        assert backport.parse_pr_source("#3456") == (3456, None)

    def test_url(self):
        pr_num, sha = backport.parse_pr_source(
            "https://github.com/redhat-developer/rhdh-plugins/pull/3456"
        )
        assert pr_num == 3456
        assert sha is None

    def test_commit_sha(self):
        pr_num, sha = backport.parse_pr_source("abc123f")
        assert pr_num is None
        assert sha == "abc123f"

    def test_invalid_exits(self):
        with pytest.raises(SystemExit):
            backport.parse_pr_source("not-valid!")
