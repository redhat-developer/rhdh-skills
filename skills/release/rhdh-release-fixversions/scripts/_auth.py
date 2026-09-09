"""Resolve Jira Basic auth from the invoker's environment — never log secrets."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

DEFAULT_JIRA_SERVER = "https://redhat.atlassian.net"


@dataclass(frozen=True)
class JiraAuth:
    login: str
    token: str
    server: str
    auth_source: str


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


def resolve_jira_auth(
    *,
    env: os._Environ[str] | None = None,
    jira_config_path: Path | None = None,
    token_file_path: Path | None = None,
) -> JiraAuth:
    """Return credentials for Jira REST. Raises RuntimeError when missing."""
    env = env or os.environ
    config_path = jira_config_path or Path.home() / ".config" / ".jira" / ".config.yml"
    file_login, file_server = _read_go_jira_config(config_path)

    login = (env.get("JIRA_EMAIL") or file_login or "").strip()
    token = (env.get("JIRA_API_TOKEN") or "").strip()
    server = (env.get("JIRA_SERVER") or file_server or DEFAULT_JIRA_SERVER).rstrip("/")
    auth_source = "JIRA_API_TOKEN" if token else ""

    embedded = _parse_email_token(token)
    if embedded:
        login, token = embedded
        auth_source = "JIRA_API_TOKEN (email:token)"

    if not token or not login:
        token_path = token_file_path if token_file_path is not None else _find_jira_token_file()
        if token_path and token_path.is_file():
            parsed = _parse_email_token(token_path.read_text(encoding="utf-8"))
            if parsed:
                login = login or parsed[0]
                token = token or parsed[1]
                auth_source = f".jira-token ({token_path})"

    if not token or not login:
        raise RuntimeError(
            "Jira auth missing. Set JIRA_EMAIL and JIRA_API_TOKEN, use ~/.config/.jira/.config.yml "
            "with JIRA_API_TOKEN, or place email:token in .jira-token next to acli. "
            "Run /setup-rhdh-skills jira to configure."
        )

    return JiraAuth(login=login, token=token, server=server, auth_source=auth_source)
