"""Tests for the rhdh-base-images shell interfaces."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = PROJECT_ROOT / "skills" / "ci" / "rhdh-base-images"
ANALYZE_SCRIPT = SKILL_DIR / "scripts" / "analyze-base-images.sh"
MAIN_SCRIPT = SKILL_DIR / "scripts" / "base-images-and-rpms.sh"

RHDH_ENV_VARS = ("RHDH_BUILD_SCRIPTS", "RHDH_REPO", "RHDH_OPERATOR_REPO")


def _clean_rhdh_env() -> dict[str, str]:
    """Return a copy of os.environ without base-images path overrides."""
    return {k: v for k, v in os.environ.items() if k not in RHDH_ENV_VARS}


def _shell_script_cmd(script: Path, *args: str) -> list[str]:
    """Build argv to run a .sh script (via bash on Windows)."""
    if os.name == "nt":
        wsl = shutil.which("wsl")
        if wsl is None:
            pytest.skip("WSL bash required to run .sh scripts on Windows")
        converted_script = subprocess.run(
            [wsl, "wslpath", "-u", script.as_posix()],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        converted_args = []
        for arg in args:
            if len(arg) >= 3 and arg[1:3] == ":\\":
                arg = subprocess.run(
                    [wsl, "wslpath", "-u", arg.replace("\\", "/")],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            converted_args.append(arg)
        return [wsl, "bash", converted_script, *converted_args]
    return [str(script), *args]


def _run_analyze(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = _clean_rhdh_env()
    if env:
        run_env.update(env)
    return subprocess.run(
        _shell_script_cmd(ANALYZE_SCRIPT, *args),
        capture_output=True,
        text=True,
        env=run_env,
    )


class TestAnalyzeBaseImagesScript:
    """Smoke tests for the bundled Bash analyzer."""

    def test_script_exists(self) -> None:
        assert ANALYZE_SCRIPT.is_file()

    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_help_prints_usage_and_exits_zero(self, flag: str) -> None:
        result = _run_analyze(flag)
        assert result.returncode == 0
        assert "Usage:" in result.stdout + result.stderr

    def test_unknown_option_exits_nonzero(self) -> None:
        result = _run_analyze("--not-a-real-flag")
        assert result.returncode != 0
        assert "Unknown option" in result.stderr

    def test_missing_workdirs_without_env_exits_nonzero(self) -> None:
        result = _run_analyze()
        assert result.returncode != 0
        assert "Set RHDH_REPO and RHDH_OPERATOR_REPO" in result.stderr

    def test_missing_build_scripts_dir_exits_nonzero(self, tmp_path: Path) -> None:
        result = _run_analyze(
            "-w",
            str(tmp_path),
            env={
                "RHDH_REPO": str(tmp_path / "rhdh"),
                "RHDH_OPERATOR_REPO": str(tmp_path / "operator"),
            },
        )
        assert result.returncode != 0
        assert "Set RHDH_BUILD_SCRIPTS" in result.stderr

    @pytest.mark.skipif(shutil.which("skopeo") is None, reason="skopeo not installed")
    def test_missing_get_latest_script_exits_nonzero(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        result = _run_analyze(
            "-s",
            str(scripts_dir),
            "-w",
            str(repo_dir),
            env=_clean_rhdh_env(),
        )
        assert result.returncode != 0
        assert "getLatestImageTags.sh not found" in result.stderr

    @pytest.mark.skipif(shutil.which("skopeo") is None, reason="skopeo not installed")
    def test_missing_repo_dir_exits_nonzero(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "getLatestImageTags.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
        (scripts_dir / "getLatestImageTags.sh").chmod(0o755)

        result = _run_analyze(
            "-s",
            str(scripts_dir),
            "-w",
            str(tmp_path / "missing-repo"),
            env=_clean_rhdh_env(),
        )
        assert result.returncode != 0
        assert "Repo not found" in result.stderr

    @pytest.mark.skipif(shutil.which("skopeo") is None, reason="skopeo not installed")
    def test_no_containerfiles_found_exits_nonzero(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "getLatestImageTags.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
        (scripts_dir / "getLatestImageTags.sh").chmod(0o755)
        repo_dir = tmp_path / "empty-repo"
        repo_dir.mkdir()

        result = _run_analyze(
            "-s",
            str(scripts_dir),
            "-w",
            str(repo_dir),
            env=_clean_rhdh_env(),
        )
        assert result.returncode != 0
        assert "No Containerfiles or Dockerfiles found" in result.stdout + result.stderr

    @staticmethod
    def _setup_mock_glit(scripts_dir: Path, output: str) -> None:
        glit = scripts_dir / "getLatestImageTags.sh"
        glit.write_text(
            f"#!/usr/bin/env bash\ncat <<'EOF'\n{output.rstrip()}\nEOF\n",
        )
        glit.chmod(0o755)

    @staticmethod
    def _write_containerfile(repo_dir: Path, tag: str) -> Path:
        cf = repo_dir / "Containerfile"
        cf.write_text(
            "# https://registry.access.redhat.com/ubi9/nodejs-24\n"
            f"FROM registry.access.redhat.com/ubi9/nodejs-24:{tag}@sha256:abc AS skeleton\n"
        )
        return cf

    @pytest.mark.skipif(shutil.which("skopeo") is None, reason="skopeo not installed")
    def test_well_formed_latest_tag_selected(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        self._setup_mock_glit(
            scripts_dir,
            "registry.access.redhat.com/ubi9/nodejs-24:1780432632\n"
            "registry.access.redhat.com/ubi9/nodejs-24:9.8-1780434037",
        )
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self._write_containerfile(repo_dir, "9.8-1780430000")

        result = _run_analyze(
            "-s",
            str(scripts_dir),
            "-w",
            str(repo_dir),
            str(repo_dir / "Containerfile"),
            env=_clean_rhdh_env(),
        )
        assert result.returncode == 0
        assert "latest:  9.8-1780434037" in result.stdout
        assert "UPDATE AVAILABLE" in result.stdout

    @pytest.mark.skipif(shutil.which("skopeo") is None, reason="skopeo not installed")
    def test_bare_numeric_current_tag_warns_and_skips(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        self._setup_mock_glit(
            scripts_dir,
            "registry.access.redhat.com/ubi9/nodejs-24:9.8-1780434037",
        )
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self._write_containerfile(repo_dir, "1780432632")

        result = _run_analyze(
            "-s",
            str(scripts_dir),
            "-w",
            str(repo_dir),
            str(repo_dir / "Containerfile"),
            env=_clean_rhdh_env(),
        )
        assert result.returncode == 0
        assert "warning: current tag is not well-formed" in result.stdout
        assert "SKIPPED (malformed current tag" in result.stdout

    @pytest.mark.skipif(shutil.which("skopeo") is None, reason="skopeo not installed")
    def test_no_well_formed_latest_skips_update(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        self._setup_mock_glit(
            scripts_dir,
            "registry.access.redhat.com/ubi9/nodejs-24:1780432632\n"
            "registry.access.redhat.com/ubi9/nodejs-24:1780439999",
        )
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self._write_containerfile(repo_dir, "9.8-1780430000")

        result = _run_analyze(
            "-s",
            str(scripts_dir),
            "-w",
            str(repo_dir),
            str(repo_dir / "Containerfile"),
            env=_clean_rhdh_env(),
        )
        assert result.returncode == 0
        assert "no well-formed x.y-z or x.y.z-z tag" in result.stdout
        assert "SKIPPED (no well-formed tag" in result.stdout


NO_SOURCES_FOUND_FOR = "No sources found for"


def _extract_bash_function(script: Path, name: str) -> str:
    """Return the named top-level `name() { ... }` body from a Bash script."""
    text = script.read_text(encoding="utf-8")
    marker = f"{name}() {{"
    start = text.find(marker)
    if start < 0:
        raise AssertionError(f"{name}() not found in {script}")
    depth = 0
    for index, char in enumerate(text[start:], start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"{name}() is unclosed in {script}")


class TestBaseImagesAndRpmsScript:
    """Smoke tests for the orchestrator --analyze flag."""

    def test_main_script_help_lists_analyze(self) -> None:
        result = subprocess.run(
            _shell_script_cmd(MAIN_SCRIPT, "--help"),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "--analyze" in result.stdout

    def test_skill_instructs_ignoring_rpm_source_warnings(self) -> None:
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        assert NO_SOURCES_FOUND_FOR in skill
        assert "no matching sources" in skill
        assert "Do not report them as unread, failed, or remaining" in skill

    def test_script_pipes_rpm_stderr_through_source_warning_filter(self) -> None:
        script = MAIN_SCRIPT.read_text(encoding="utf-8")
        assert 'filter_rpm_lockfile_source_warnings <"${rpm_err}"' in script

    def test_filter_rpm_lockfile_source_warnings_drops_noise(self) -> None:
        function = _extract_bash_function(MAIN_SCRIPT, "filter_rpm_lockfile_source_warnings")
        noise = (
            f"WARNING:rpm_lockfile:{NO_SOURCES_FOUND_FOR} "
            "kernel-headers-5.14.0-687.41.1.el9_8.x86_64\n"
            f"WARNING:rpm_lockfile:{NO_SOURCES_FOUND_FOR} efi-srpm-macros-6-4.el9.noarch\n"
            "note: no matching sources for kernel-headers\n"
            "error: dnf transaction failed\n"
        )
        result = subprocess.run(
            ["bash", "-c", f"{function}\nfilter_rpm_lockfile_source_warnings"],
            input=noise,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "error: dnf transaction failed\n"

    def test_latest_openshift_el9_beta_stream_from_listing_picks_highest(self) -> None:
        function = _extract_bash_function(
            MAIN_SCRIPT, "latest_openshift_el9_beta_stream_from_listing"
        )
        listing = (
            '<a href="4.19-el9-beta/">4.19-el9-beta/</a>\n'
            '<a href="4.21-el9-beta/">4.21-el9-beta/</a>\n'
            '<a href="4.22-el9-beta/">4.22-el9-beta/</a>\n'
            '<a href="4.9-el9-beta/">4.9-el9-beta/</a>\n'
        )
        result = subprocess.run(
            ["bash", "-c", f"{function}\nlatest_openshift_el9_beta_stream_from_listing"],
            input=listing,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "4.22-el9-beta"

    def test_bump_openshift_rpm_repos_in_file_rewrites_url_and_repoid(self, tmp_path: Path) -> None:
        function = _extract_bash_function(MAIN_SCRIPT, "bump_openshift_rpm_repos_in_file")
        rpms_in = tmp_path / "rpms.in.yaml"
        rpms_in.write_text(
            "    - repoid: rhocp-4.21-for-rhel-9-$basearch-rpms\n"
            "      baseurl: https://mirror.openshift.com/pub/openshift-v4/"
            "$basearch/dependencies/rpms/4.21-el9-beta/\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'{function}\nbump_openshift_rpm_repos_in_file "$1" "$2"',
                "bash",
                str(rpms_in),
                "4.22-el9-beta",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        text = rpms_in.read_text(encoding="utf-8")
        assert "4.22-el9-beta" in text
        assert "rhocp-4.22-for-rhel-9-$basearch-rpms" in text
        assert "4.21-el9-beta" not in text
        assert "rhocp-4.21-for-rhel-9-" not in text

    def test_bump_openshift_rpm_repos_in_file_noop_when_already_latest(
        self, tmp_path: Path
    ) -> None:
        function = _extract_bash_function(MAIN_SCRIPT, "bump_openshift_rpm_repos_in_file")
        original = (
            "    - repoid: rhocp-4.22-for-rhel-9-$basearch-rpms\n"
            "      baseurl: https://mirror.openshift.com/pub/openshift-v4/"
            "$basearch/dependencies/rpms/4.22-el9-beta/\n"
        )
        rpms_in = tmp_path / "rpms.in.yaml"
        rpms_in.write_text(original, encoding="utf-8")
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'{function}\nbump_openshift_rpm_repos_in_file "$1" "$2"',
                "bash",
                str(rpms_in),
                "4.22-el9-beta",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert rpms_in.read_text(encoding="utf-8") == original

    def test_skill_covers_openshift_el9_beta_rpm_bump(self) -> None:
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        assert "N-el9-beta" in skill
        script = MAIN_SCRIPT.read_text(encoding="utf-8")
        assert "bump_openshift_rpm_repos" in script
        assert (
            'commit_push_paths "${branch}" "chore: update rpms.lock.yaml [skip-build]" rpms.lock.yaml rpms.in.yaml'
            in script
        )

    def test_skill_forbids_go_toolchain_downgrade(self) -> None:
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        assert "Never lower `go` or `toolchain`" in skill
        script = MAIN_SCRIPT.read_text(encoding="utf-8")
        assert "will not downgrade" in script

    def test_catalog_git_branch_for_maps_release_line(self) -> None:
        function = _extract_bash_function(MAIN_SCRIPT, "catalog_git_branch_for")
        cases = (
            ("main", "main"),
            ("release-1.10", "rhdh-1.10-rhel-9"),
            ("release-2.1", "release-2.1"),
        )
        for github_branch, catalog_branch in cases:
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    (
                        'die() { echo "$*" >&2; exit 1; }\n'
                        f"{function}\ncatalog_git_branch_for {github_branch}"
                    ),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == catalog_branch

    def test_detect_repo_kind_plugin_catalog(self, tmp_path: Path) -> None:
        function = _extract_bash_function(MAIN_SCRIPT, "detect_repo_kind")
        repo = tmp_path / "catalog"
        (repo / "build" / "containerfiles").mkdir(parents=True)
        (repo / ".tekton").mkdir()
        (repo / "build" / "containerfiles" / "builder.Containerfile").write_text("FROM x\n")
        (repo / ".nvmrc").write_text("24.19.0\n")
        (repo / ".tekton" / "updatePLRs.sh").write_text("#!/bin/bash\n")
        result = subprocess.run(
            ["bash", "-c", f'{function}\ndetect_repo_kind "$1"', "bash", str(repo)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "rhdh-plugin-catalog"

    def test_detect_repo_kind_overlays(self, tmp_path: Path) -> None:
        function = _extract_bash_function(MAIN_SCRIPT, "detect_repo_kind")
        repo = tmp_path / "overlays"
        repo.mkdir()
        (repo / "workspaces").mkdir()
        (repo / "versions.json").write_text('{\n    "node": "24.14.0"\n}\n')
        result = subprocess.run(
            ["bash", "-c", f'{function}\ndetect_repo_kind "$1"', "bash", str(repo)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "rhdh-plugin-export-overlays"

    def test_skill_covers_catalog_and_overlays(self) -> None:
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        assert "plugin-catalog" in skill
        assert "versions.json" in skill
        repos = (SKILL_DIR / "references" / "repos.md").read_text(encoding="utf-8")
        assert "rhidp/rhdh-plugin-catalog" in repos
        assert "rhdh-plugin-export-overlays" in repos
        assert "Not this skill: rhdh-plugin-catalog" not in repos

    def test_nodejs_builder_image_accepts_ubi10(self, tmp_path: Path) -> None:
        function = _extract_bash_function(MAIN_SCRIPT, "rhdh_nodejs_builder_image")
        cf = tmp_path / "Containerfile"
        cf.write_text(
            "FROM registry.access.redhat.com/ubi10/nodejs-24:10.0-1@sha256:abc AS skeleton\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'{function}\nrhdh_nodejs_builder_image "$1"',
                "bash",
                str(cf),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "ubi10/nodejs-24:10.0-1@sha256:abc" in result.stdout


class TestGoVersionGte:
    """Forward-only Go toolchain compares used before editing operator go.mod."""

    @staticmethod
    def _gte(left: str, right: str) -> int:
        function = _extract_bash_function(MAIN_SCRIPT, "go_version_gte")
        quoted_left = "''" if left == "" else left
        quoted_right = "''" if right == "" else right
        result = subprocess.run(
            ["bash", "-c", f"{function}\ngo_version_gte {quoted_left} {quoted_right}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode

    def test_newer_patch_is_gte(self) -> None:
        assert self._gte("1.26.6", "1.26.5") == 0

    def test_older_patch_is_not_gte(self) -> None:
        assert self._gte("1.26.5", "1.26.6") == 1

    def test_equal_is_gte(self) -> None:
        assert self._gte("1.26.5", "1.26.5") == 0

    def test_strips_go_prefix(self) -> None:
        assert self._gte("go1.26.6", "1.26.5") == 0

    def test_empty_is_not_gte(self) -> None:
        assert self._gte("", "1.26.5") == 1
