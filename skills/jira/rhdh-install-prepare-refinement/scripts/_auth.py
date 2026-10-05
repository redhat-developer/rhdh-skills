"""Resolve Jira Basic auth from the invoker environment (stdlib only)."""

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


def _parse_email_token(text: str) -> tuple[str, str] | None:
    text = text.strip()
    if not text:
        return None
    at = text.find("@")
    colon = text.find(":", at if at > 0 else 0)
    if at > 0 and colon > at:
        return text[:colon].strip(), text[colon + 1 :].strip()
    return None


def _read_go_jira_config(path: Path) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    login = re.search(r"^login:\s*(.+)$", text, re.MULTILINE)
    return login.group(1).strip() if login else None


def _read_acli_jira_config(path: Path) -> tuple[str, str]:
    """Return (email, token) from ~/.config/acli/jira_config.yaml if present."""
    if not path.is_file():
        return "", ""
    text = path.read_text(encoding="utf-8")
    email = ""
    token = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("email:"):
            email = stripped.split(":", 1)[1].strip().strip("'\"")
        elif stripped.startswith("token:"):
            token = stripped.split(":", 1)[1].strip().strip("'\"")
    return email, token


def _find_jira_token_file() -> Path | None:
    candidates: list[Path] = []
    acli = shutil.which("acli")
    if acli:
        candidates.append(Path(acli).resolve().parent / ".jira-token")
    candidates.extend(
        [
            Path.home() / ".config" / "acli" / ".jira-token",
            Path.home() / ".local" / "bin" / ".jira-token",
            Path.home() / ".jira-token",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def resolve_jira_auth(env: os._Environ[str] | None = None) -> JiraAuth:
    env = env or os.environ
    login = (env.get("JIRA_EMAIL") or "").strip()
    token = (env.get("JIRA_API_TOKEN") or env.get("JIRA_TOKEN") or "").strip()

    embedded = _parse_email_token(token)
    if embedded:
        login, token = embedded

    if not login:
        login = _read_go_jira_config(Path.home() / ".config" / ".jira" / ".config.yml") or ""

    if not token or not login:
        acli_email, acli_token = _read_acli_jira_config(
            Path.home() / ".config" / "acli" / "jira_config.yaml"
        )
        login = login or acli_email
        token = token or acli_token

    if not token or not login:
        token_path = _find_jira_token_file()
        if token_path:
            parsed = _parse_email_token(token_path.read_text(encoding="utf-8"))
            if parsed:
                login = login or parsed[0]
                token = token or parsed[1]

    if not login or not token:
        raise SystemExit(
            "Jira auth missing for live Jira.\n"
            "  • export JIRA_EMAIL and JIRA_API_TOKEN (Atlassian API token)\n"
            "  • or ~/.jira-token or ~/.config/acli/.jira-token as email:token\n"
            "  • or ~/.config/acli/jira_config.yaml (email + token)\n"
            "  • or install acli and configure API token auth\n"
            "Offline: use --fixture fixtures/refinement-queue.sample.json"
        )

    server = (env.get("JIRA_BASE_URL") or DEFAULT_JIRA_SERVER).rstrip("/")
    return JiraAuth(login=login, token=token, server=server)
