"""Tests for the rhdh-base-images GitLab runner rebuild script interface."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = PROJECT_ROOT / "skills" / "ci" / "rhdh-base-images"
RUNNER_SCRIPT = SKILL_DIR / "scripts" / "rebuildGitlabRunner.sh"


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
        return [wsl, "bash", converted_script, *args]
    return [str(script), *args]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _shell_script_cmd(RUNNER_SCRIPT, *args),
        capture_output=True,
        text=True,
    )


def _fake_checkout(tmp_path: Path, name: str, branch: str) -> Path:
    """Create a minimal git checkout on the named branch."""
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", branch, str(repo)], check=True)
    (repo / ".gitkeep").write_text("")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"],
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    return repo


class TestRebuildGitlabRunnerScript:
    """Interface tests for the runner rebuild script."""

    def test_script_exists(self) -> None:
        assert RUNNER_SCRIPT.is_file()

    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_help_prints_usage_and_exits_zero(self, flag: str) -> None:
        result = _run(flag)
        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_unknown_option_exits_nonzero(self) -> None:
        result = _run("--nope")
        assert result.returncode != 0
        assert "unknown parameter" in result.stdout + result.stderr

    def test_missing_required_args_exit_nonzero(self) -> None:
        result = _run()
        assert result.returncode != 0
        assert "--rhdh is required" in result.stdout + result.stderr

    def test_requires_rhdh_containerfile_layout(self, tmp_path: Path) -> None:
        result = _run("--rhdh", str(tmp_path), "-b", "release-2.1", "--version", "2.1")
        assert result.returncode != 0
        assert "not an rhdh checkout" in result.stdout + result.stderr

    def test_branch_guard_rejects_wrong_branch(self, tmp_path: Path) -> None:
        rhdh = _fake_checkout(tmp_path, "rhdh", "release-2.1")
        (rhdh / "build" / "containerfiles").mkdir(parents=True)
        (rhdh / "build" / "containerfiles" / "gitlab-runner.Containerfile").write_text(
            "FROM quay.io/rhdh/plugin-catalog-builder-rhel10:2.1\n"
        )
        result = _run("--rhdh", str(rhdh), "-b", "main", "--version", "2.2")
        assert result.returncode != 0
        assert "is on branch 'release-2.1', not 'main'" in result.stdout + result.stderr

    def test_dry_run_completes_with_shims(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With shimmed skopeo/podman, a dry run pins, plans, and re-pins without network."""
        rhdh = _fake_checkout(tmp_path, "rhdh", "release-2.1")
        cf_dir = rhdh / "build" / "containerfiles"
        cf_dir.mkdir(parents=True)
        (cf_dir / "gitlab-runner.Containerfile").write_text(
            "FROM quay.io/rhdh/plugin-catalog-builder-rhel10:2.1\n"
        )
        catalog = _fake_checkout(tmp_path, "rhdh-plugin-catalog", "release-2.1")
        (catalog / ".gitlab-ci.yml").write_text("image: quay.io/rhdh/gitlab-runner:2.1\n")

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "skopeo").write_text(
            "#!/usr/bin/env bash\n"
            'case "$1" in\n'
            '  list-tags) printf \'{"Tags":["2.1-9","2.1-10"]}\' ;;\n'
            '  inspect) printf \'{"Digest":"sha256:abc123"}\' ;;\n'
            "esac\n"
        )
        (bin_dir / "podman").write_text("#!/usr/bin/env bash\nexit 0\n")
        for shim in ("skopeo", "podman"):
            (bin_dir / shim).chmod(0o755)
        run_env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

        result = subprocess.run(
            _shell_script_cmd(
                RUNNER_SCRIPT,
                "--rhdh",
                str(rhdh),
                "-b",
                "release-2.1",
                "--version",
                "2.1",
                "--bump-ci",
                str(catalog),
                "--dry-run",
            ),
            capture_output=True,
            text=True,
            env=run_env,
        )
        assert result.returncode == 0, result.stderr
        assert (
            "builder = quay.io/rhdh/plugin-catalog-builder-rhel10:2.1-10@sha256:abc123"
            in result.stdout
        )
        assert "pin|" in result.stdout
        assert "build|" in result.stdout
        assert f"ci|{catalog / '.gitlab-ci.yml'}|" in result.stdout.replace(" ", "")
        # dry run must not edit anything
        assert (
            cf_dir / "gitlab-runner.Containerfile"
        ).read_text() == "FROM quay.io/rhdh/plugin-catalog-builder-rhel10:2.1\n"
