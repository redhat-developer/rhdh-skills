"""Tests for rhdh-konflux-tasks check-trusted-tasks.sh."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    PROJECT_ROOT / "skills" / "ci" / "rhdh-konflux-tasks" / "scripts" / "check-trusted-tasks.sh"
)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "check_trusted_tasks"
NOW = "2026-08-27T00:00:00Z"


def _cmd(script: Path, *args: str) -> list[str]:
    if os.name == "nt":
        pytest.skip("bash required")
    return [str(script), *args]


def _run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    if not shutil.which("jq"):
        pytest.skip("jq is required")
    return subprocess.run(
        _cmd(SCRIPT, *args),
        capture_output=True,
        text=True,
        check=check,
    )


def test_script_exists() -> None:
    assert SCRIPT.is_file()


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_prints_usage_and_exits_zero(flag: str) -> None:
    result = _run(flag)
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_unknown_option_exits_two() -> None:
    result = _run("--not-a-real-flag")
    assert result.returncode == 2
    assert "Unknown option" in result.stderr


def test_classifies_fixture_statuses() -> None:
    result = _run(
        "--data-file",
        str(FIXTURES / "trusted.json"),
        "--now",
        NOW,
        "--horizon-days",
        "14",
        "--json",
        str(FIXTURES / "pipeline.yaml"),
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    by_task = {row["task"]: row["status"] for row in payload["results"]}
    assert by_task["task-good"] == "trusted"
    assert by_task["task-successor"] == "expired"
    assert by_task["task-expiring"] == "expiring-no-successor"
    assert by_task["task-dead"] == "expired-no-successor"
    assert by_task["task-missing"] == "untrusted"
    assert "Slack #konflux-users" in result.stderr
    assert "expires on 2026-09-05T00:00:00Z" in result.stderr
    assert "horizon is 14 days" in result.stderr


def test_expiring_no_successor_exits_zero_when_alone(tmp_path: Path) -> None:
    yaml_path = tmp_path / "only-expiring.yaml"
    yaml_path.write_text(
        "spec:\n  tasks:\n  - taskRef:\n      params:\n"
        "      - name: bundle\n"
        "        value: quay.io/konflux-ci/tekton-catalog/task-expiring:0.1"
        "@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd\n"
    )
    result = _run(
        "--data-file",
        str(FIXTURES / "trusted.json"),
        "--now",
        NOW,
        "--horizon-days",
        "14",
        "--json",
        str(yaml_path),
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["results"][0]["status"] == "expiring-no-successor"
    assert "ask in Slack #konflux-users" in result.stderr


def test_apply_rewrites_same_tag_digest_only(tmp_path: Path) -> None:
    dest = tmp_path / "pipeline.yaml"
    dest.write_text((FIXTURES / "pipeline.yaml").read_text())
    result = _run(
        "--data-file",
        str(FIXTURES / "trusted.json"),
        "--now",
        NOW,
        "--horizon-days",
        "14",
        "--apply-trusted-digests",
        str(dest),
    )
    assert result.returncode == 1
    text = dest.read_text()
    assert (
        "task-successor:0.2@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        in text
    )
    assert (
        "task-successor:0.2@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        not in text
    )
    assert (
        "task-missing:0.2@sha256:1111111111111111111111111111111111111111111111111111111111111111"
        in text
    )


def test_print_digest_picks_usable_with_buffer() -> None:
    result = _run(
        "--data-file",
        str(FIXTURES / "trusted.json"),
        "--now",
        NOW,
        "--horizon-days",
        "14",
        "--print-digest",
        "quay.io/konflux-ci/tekton-catalog/task-successor:0.2",
    )
    assert result.returncode == 0
    assert result.stdout.strip() == (
        "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    )
