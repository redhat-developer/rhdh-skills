"""Jira auth resolution for release-manager CLIs (production vs staging)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

AUTH_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "release"
    / "rhdh-release-fixversions"
    / "scripts"
    / "_auth.py"
)


def load_auth():
    spec = importlib.util.spec_from_file_location("jira_release_auth", AUTH_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["jira_release_auth"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def auth_mod():
    return load_auth()


def test_production_uses_redhat_default(auth_mod, monkeypatch):
    env = {
        "JIRA_EMAIL": "user@example.com",
        "JIRA_API_TOKEN": "atlassian-api-token",
    }
    monkeypatch.delenv("JIRA_STAGING_URL", raising=False)
    result = auth_mod.resolve_jira_auth(
        staging=False, env=env, token_file_path=Path("/nonexistent")
    )
    assert result.deployment == "production"
    assert result.server == "https://redhat.atlassian.net"


def test_staging_uses_staging_url_with_production_token(auth_mod):
    env = {
        "JIRA_STAGING_URL": "https://jira-stage.example.com",
        "JIRA_EMAIL": "user@example.com",
        "JIRA_API_TOKEN": "prod-token",
    }
    result = auth_mod.resolve_jira_auth(staging=True, env=env, token_file_path=Path("/nonexistent"))
    assert result.deployment == "staging"
    assert result.server == "https://jira-stage.example.com"
    assert result.login == "user@example.com"
    assert result.token == "prod-token"


def test_staging_optional_token_override(auth_mod):
    env = {
        "JIRA_STAGING_URL": "https://jira-stage.example.com",
        "JIRA_STAGING_TOKEN": "user@example.com:staging-token",
        "JIRA_EMAIL": "user@example.com",
        "JIRA_API_TOKEN": "prod-token",
    }
    result = auth_mod.resolve_jira_auth(staging=True, env=env)
    assert result.deployment == "staging"
    assert result.login == "user@example.com"
    assert result.token == "staging-token"


def test_jira_use_staging_env_enables_staging(auth_mod):
    env = {
        "JIRA_USE_STAGING": "true",
        "JIRA_STAGING_URL": "https://jira-stage.example.com",
        "JIRA_EMAIL": "user@example.com",
        "JIRA_API_TOKEN": "tok",
    }
    assert auth_mod.staging_enabled(False, env) is True
    result = auth_mod.resolve_jira_auth(
        staging=False, env=env, token_file_path=Path("/nonexistent")
    )
    assert result.deployment == "staging"


def test_staging_missing_url_raises(auth_mod):
    env = {
        "JIRA_EMAIL": "user@example.com",
        "JIRA_API_TOKEN": "tok",
    }
    with pytest.raises(RuntimeError, match="JIRA_STAGING_URL"):
        auth_mod.resolve_jira_auth(staging=True, env=env)


def _load_cli_module(relative: str, module_name: str):
    path = Path(__file__).resolve().parents[2] / relative
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_fixversions_parser_accepts_staging_flag():
    module = _load_cli_module(
        "skills/release/rhdh-release-fixversions/scripts/fixversions.py",
        "fixversions_cli",
    )
    args = module.build_parser().parse_args(["check", "--staging", "--json"])
    assert args.staging is True
    assert args.command == "check"
