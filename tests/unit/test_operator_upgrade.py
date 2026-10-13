"""Tests for rhdh-smoke-tests operator_upgrade.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    PROJECT_ROOT / "skills" / "release" / "rhdh-smoke-tests" / "scripts" / "operator_upgrade.py"
)
SPEC = importlib.util.spec_from_file_location("operator_upgrade", SCRIPT)
assert SPEC and SPEC.loader
UPGRADE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPGRADE)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_script_exists() -> None:
    assert SCRIPT.is_file()


def test_subscription_patch_omits_empty_starting_csv() -> None:
    assert UPGRADE.subscription_patch("fast-1.10", None) == {"spec": {"channel": "fast-1.10"}}
    assert UPGRADE.subscription_patch("fast-1.10", "rhdh-operator.v1.10.4") == {
        "spec": {"channel": "fast-1.10", "startingCSV": "rhdh-operator.v1.10.4"},
    }


def test_unapproved_installplans_only_explicit_false() -> None:
    payload = {
        "items": [
            {"metadata": {"name": "skip-approved"}, "spec": {"approved": True}},
            {"metadata": {"name": "skip-missing"}, "spec": {}},
            {"metadata": {"name": "need-approve"}, "spec": {"approved": False}},
        ]
    }
    assert UPGRADE.unapproved_installplans(payload) == ["need-approve"]
    assert UPGRADE.unapproved_installplans(None) == []


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_prints_usage_and_exits_zero(flag: str) -> None:
    result = _run(flag)
    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
    assert "--channel" in result.stdout


def test_missing_channel_exits_two() -> None:
    result = _run()
    assert result.returncode == 2
    assert "--channel" in result.stderr


def test_unknown_option_exits_two() -> None:
    result = _run("--channel", "fast", "--not-a-real-flag")
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_dry_run_prints_patch_and_skips_oc() -> None:
    result = _run(
        "--dry-run",
        "--json",
        "--channel",
        "fast-1.10",
        "--starting-csv",
        "rhdh-operator.v1.10.4",
    )
    assert result.returncode == 0
    assert "patch subscription rhdh" in result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["dryRun"] is True
    assert payload["channel"] == "fast-1.10"
    assert payload["startingCSV"] == "rhdh-operator.v1.10.4"
