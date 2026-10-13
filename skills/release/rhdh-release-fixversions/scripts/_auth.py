"""Resolve Jira Basic auth from the invoker's environment — never log secrets."""

from __future__ import annotations

import argparse
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

DEFAULT_JIRA_SERVER = "https://redhat.atlassian.net"
DEPLOYMENT_PRODUCTION = "production"
DEPLOYMENT_STAGING = "staging"


@dataclass(frozen=True)
class JiraAuth:
    login: str
    token: str
    server: str
    auth_source: str
    deployment: str = DEPLOYMENT_PRODUCTION


def _parse_email_token(text: str) -> tuple[str, str] | None:
    text = text.strip()
    if not text:
        return None
    at = text.find("@")
    colon = text.find(":", at if at > 0 else 0)
    if at > 0 and colon > at:
        return text[:colon].strip(), text[colon + 1 :].strip()
    return None


def _read_go_jira_config(path: Path) -> tuple[str | None, str | None]:
    if not path.is_file():
        return None, None
    text = path.read_text(encoding="utf-8")
    login = re.search(r"^login:\s*(.+)$", text, re.MULTILINE)
    server = re.search(r"^server:\s*(.+)$", text, re.MULTILINE)
    login_val = login.group(1).strip() if login else None
    server_val = server.group(1).strip().rstrip("/") if server else None
    return login_val, server_val


def _find_jira_token_file() -> Path | None:
    candidates: list[Path] = []
    acli = shutil.which("acli")
    if acli:
        candidates.append(Path(acli).resolve().parent / ".jira-token")
        candidates.append(Path(acli).parent / ".jira-token")
    home = Path.home()
    candidates.extend(
        [
            home / ".local" / "bin" / ".jira-token",
            home / ".jira-token",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def staging_enabled(cli_staging: bool, env: os._Environ[str]) -> bool:
    if cli_staging:
        return True
    flag = env.get("JIRA_USE_STAGING", "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def add_deployment_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--staging",
        action="store_true",
        help=(
            "Target staging Jira (JIRA_STAGING_URL; same JIRA_EMAIL/JIRA_API_TOKEN as "
            "production unless JIRA_STAGING_* overrides are set)."
        ),
    )


def _resolve_login_and_token(
    env: os._Environ[str],
    file_login: str | None,
    token_file_path: Path | None,
) -> tuple[str, str, str]:
    login = (env.get("JIRA_EMAIL") or file_login or "").strip()
    token = (env.get("JIRA_API_TOKEN") or env.get("JIRA_TOKEN") or "").strip()
    auth_source = "JIRA_API_TOKEN" if token else ""

    embedded = _parse_email_token(token)
    if embedded:
        login, token = embedded
        auth_source = f"{auth_source} (email:token)" if auth_source else "email:token"

    if not token or not login:
        token_path = token_file_path if token_file_path is not None else _find_jira_token_file()
        if token_path and token_path.is_file():
            parsed = _parse_email_token(token_path.read_text(encoding="utf-8"))
            if parsed:
                login = login or parsed[0]
                token = token or parsed[1]
                auth_source = f".jira-token ({token_path})"

    return login, token, auth_source


def _apply_staging_token_overrides(
    env: os._Environ[str],
    login: str,
    token: str,
    auth_source: str,
) -> tuple[str, str, str]:
    staging_token = (
        env.get("JIRA_STAGING_TOKEN") or env.get("JIRA_STAGING_API_TOKEN") or ""
    ).strip()
    if staging_token:
        token = staging_token
        auth_source = "JIRA_STAGING_TOKEN"
        embedded = _parse_email_token(token)
        if embedded:
            login, token = embedded
            auth_source = f"{auth_source} (email:token)"
    staging_email = (env.get("JIRA_STAGING_EMAIL") or "").strip()
    if staging_email:
        login = staging_email
    return login, token, auth_source


def resolve_jira_auth(
    *,
    staging: bool = False,
    env: os._Environ[str] | None = None,
    jira_config_path: Path | None = None,
    token_file_path: Path | None = None,
) -> JiraAuth:
    """Return credentials for Jira REST. Raises RuntimeError when missing."""
    env = env or os.environ
    use_staging = staging_enabled(staging, env)
    config_path = jira_config_path or Path.home() / ".config" / ".jira" / ".config.yml"
    file_login, file_server = _read_go_jira_config(config_path)

    login, token, auth_source = _resolve_login_and_token(env, file_login, token_file_path)

    if use_staging:
        server = (env.get("JIRA_STAGING_URL") or "").strip().rstrip("/")
        if not server:
            raise RuntimeError(
                "Staging Jira URL missing. Set JIRA_STAGING_URL when using --staging "
                "or JIRA_USE_STAGING."
            )
        login, token, auth_source = _apply_staging_token_overrides(env, login, token, auth_source)
        deployment = DEPLOYMENT_STAGING
    else:
        server = (env.get("JIRA_SERVER") or file_server or DEFAULT_JIRA_SERVER).rstrip("/")
        deployment = DEPLOYMENT_PRODUCTION

    if not token or not login:
        if use_staging:
            raise RuntimeError(
                "Staging Jira auth missing. Set JIRA_STAGING_URL and the same "
                "JIRA_EMAIL/JIRA_API_TOKEN (or .jira-token) as production. "
                "Optional: JIRA_STAGING_EMAIL or JIRA_STAGING_TOKEN overrides."
            )
        raise RuntimeError(
            "Jira auth missing. Set JIRA_EMAIL and JIRA_API_TOKEN, use ~/.config/.jira/.config.yml "
            "with JIRA_API_TOKEN, or place email:token in .jira-token next to acli. "
            "Run /setup-rhdh-skills jira to configure."
        )

    return JiraAuth(
        login=login,
        token=token,
        server=server,
        auth_source=auth_source,
        deployment=deployment,
    )
