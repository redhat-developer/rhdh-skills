"""Resolve Jira auth: API token env/files, or authenticated acli session."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_JIRA_SERVER = "https://redhat.atlassian.net"


@dataclass(frozen=True)
class JiraAuth:
    login: str
    token: str
    server: str
    via_acli: bool = False


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


def _read_acli_flat_config(path: Path) -> tuple[str, str]:
    """Legacy top-level email/token in jira_config.yaml."""
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


def _read_acli_profile_email(path: Path) -> str:
    """Email from first profile entry (acli 1.x stores token in OS keyring)."""
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^\s+email:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip().strip("'\"") if match else ""


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


def _acli_session_ok() -> bool:
    if not shutil.which("acli"):
        return False
    result = subprocess.run(
        ["acli", "jira", "project", "list", "--recent", "1"],
        capture_output=True,
        text=True,
        timeout=45,
    )
    return result.returncode == 0


def resolve_jira_auth(env: os._Environ[str] | None = None) -> JiraAuth:
    env = env or os.environ
    login = (env.get("JIRA_EMAIL") or "").strip()
    token = (env.get("JIRA_API_TOKEN") or env.get("JIRA_TOKEN") or "").strip()

    embedded = _parse_email_token(token)
    if embedded:
        login, token = embedded

    if not login:
        login = _read_go_jira_config(Path.home() / ".config" / ".jira" / ".config.yml") or ""

    acli_cfg = Path.home() / ".config" / "acli" / "jira_config.yaml"
    if not token or not login:
        acli_email, acli_token = _read_acli_flat_config(acli_cfg)
        login = login or acli_email
        token = token or acli_token

    if not token or not login:
        token_path = _find_jira_token_file()
        if token_path:
            parsed = _parse_email_token(token_path.read_text(encoding="utf-8"))
            if parsed:
                login = login or parsed[0]
                token = token or parsed[1]

    server = (env.get("JIRA_BASE_URL") or DEFAULT_JIRA_SERVER).rstrip("/")

    if login and token:
        return JiraAuth(login=login, token=token, server=server, via_acli=False)

    if _acli_session_ok():
        login = login or _read_acli_profile_email(acli_cfg)
        return JiraAuth(login=login, token="", server=server, via_acli=True)

    lines = ["Jira auth missing for live Jira."]
    if shutil.which("acli"):
        lines.append(
            "  acli is on PATH but not authenticated. Run:\n"
            "    acli jira auth login --site redhat.atlassian.net "
            "--email <you@redhat.com> --token"
        )
        lines.append("  Or: acli jira auth login   (interactive)")
    else:
        lines.append("  • install acli, or export JIRA_EMAIL + JIRA_API_TOKEN")
    lines.append("  Offline: --fixture tests/fixtures/install_refinement_queue.json")
    raise SystemExit("\n".join(lines))
