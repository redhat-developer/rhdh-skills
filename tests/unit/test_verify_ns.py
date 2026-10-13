"""Tests for rhdh-smoke-tests verify_ns.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "skills" / "release" / "rhdh-smoke-tests" / "scripts" / "verify_ns.py"
SPEC = importlib.util.spec_from_file_location("verify_ns", SCRIPT)
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_script_exists() -> None:
    assert SCRIPT.is_file()


def test_guest_token_prefers_backstage_identity() -> None:
    assert VERIFY.guest_token({"backstageIdentity": {"token": "abc"}, "token": "other"}) == "abc"
    assert VERIFY.guest_token({"token": "xyz"}) == "xyz"
    assert VERIFY.guest_token("not-json") == ""
    assert VERIFY.guest_token(None) == ""


def test_packages_len_prefers_total_items() -> None:
    assert VERIFY.packages_len({"totalItems": 59, "items": [{}]}) == 59
    assert VERIFY.packages_len({"totalItems": "59", "items": []}) == 59
    assert VERIFY.packages_len({"items": [1, 2, 3]}) == 3
    assert VERIFY.packages_len([{}, {}]) == 2
    assert VERIFY.packages_len(None) == 0
    assert VERIFY.packages_len("not-json") == 0


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_prints_usage_and_exits_zero(flag: str) -> None:
    result = _run(flag)
    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
    assert "--namespace" in result.stdout


def test_missing_namespace_exits_two() -> None:
    result = _run()
    assert result.returncode == 2
    assert "--namespace" in result.stderr


def test_unknown_option_exits_two() -> None:
    result = _run("--namespace", "ns", "--not-a-real-flag")
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
