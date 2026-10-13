"""Tests for rhdh-smoke-tests cluster_from_console.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    PROJECT_ROOT / "skills" / "release" / "rhdh-smoke-tests" / "scripts" / "cluster_from_console.py"
)
SPEC = importlib.util.spec_from_file_location("cluster_from_console", SCRIPT)
assert SPEC and SPEC.loader
CLUSTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLUSTER)

EXAMPLE = "https://console-openshift-console.apps.ci-ln-ibvnlsb-72292.gcp-2.ci.openshift.org/"
EXAMPLE_ROUTER = "apps.ci-ln-ibvnlsb-72292.gcp-2.ci.openshift.org"
EXAMPLE_TOKEN = (
    "https://oauth-openshift.apps.ci-ln-ibvnlsb-72292.gcp-2.ci.openshift.org/oauth/token/display"
)
EXAMPLE_API = "https://api.ci-ln-ibvnlsb-72292.gcp-2.ci.openshift.org:6443"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_script_exists() -> None:
    assert SCRIPT.is_file()


def test_parse_example_console_url() -> None:
    got = CLUSTER.parse_console_url(EXAMPLE)
    assert got == {
        "clusterRouterBase": EXAMPLE_ROUTER,
        "tokenDisplayUrl": EXAMPLE_TOKEN,
        "apiServer": EXAMPLE_API,
    }


def test_parse_apps_host_and_oauth_host() -> None:
    from_apps = CLUSTER.parse_console_url(f"https://{EXAMPLE_ROUTER}/")
    from_oauth = CLUSTER.parse_console_url(
        "https://oauth-openshift.apps.ci-ln-ibvnlsb-72292.gcp-2.ci.openshift.org/"
        "oauth/token/display",
    )
    assert from_apps["clusterRouterBase"] == EXAMPLE_ROUTER
    assert from_oauth["clusterRouterBase"] == EXAMPLE_ROUTER


def test_parse_rejects_empty_and_unrelated() -> None:
    assert CLUSTER.parse_console_url("") == {}
    assert CLUSTER.parse_console_url("https://example.com/") == {}
    assert CLUSTER.parse_console_url("https://console-openshift-console.apps/") == {}


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_prints_usage_and_exits_zero(flag: str) -> None:
    result = _run(flag)
    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()


def test_json_stdout_and_key_equals() -> None:
    json_result = _run("--json", EXAMPLE)
    assert json_result.returncode == 0
    payload = json.loads(json_result.stdout)
    assert payload["clusterRouterBase"] == EXAMPLE_ROUTER
    assert payload["apiServer"] == EXAMPLE_API

    plain = _run(EXAMPLE)
    assert plain.returncode == 0
    assert f"clusterRouterBase={EXAMPLE_ROUTER}" in plain.stdout
    assert f"tokenDisplayUrl={EXAMPLE_TOKEN}" in plain.stdout
    assert f"apiServer={EXAMPLE_API}" in plain.stdout


def test_bad_url_exits_two() -> None:
    result = _run("https://not-a-console.example/")
    assert result.returncode == 2
    assert "not an OpenShift console URL" in result.stderr
