"""Authenticated Jira client for the RHDH lint skill.

This is the skill-local authenticated adapter. It owns token discovery and
authenticated HTTP requests; callers never handle credentials directly. The
Jira host is fixed to the Red Hat instance.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

JIRA_HOST = "https://redhat.atlassian.net"


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise JiraClientError(f"refusing redirect from {JIRA_HOST} to {newurl}", status=code)


class JiraClientError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def find_token_file(acli_path: str | None = None) -> Path | None:
    override = os.environ.get("JIRA_TOKEN_FILE")
    if override:
        path = Path(override)
        return path if path.is_file() else None
    if not acli_path:
        acli_path = shutil.which("acli")
    if not acli_path:
        return None
    token_path = Path(acli_path).resolve().parent / ".jira-token"
    return token_path if token_path.is_file() else None


def load_email_token() -> str:
    path = find_token_file()
    if path is None:
        raise JiraClientError(
            "Jira token file not found next to acli (or JIRA_TOKEN_FILE); "
            "run /setup-rhdh-skills atlassian-mcp or authenticate acli."
        )
    try:
        line = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError) as exc:
        raise JiraClientError(f"could not read the Jira token file: {exc}") from exc
    if ":" not in line:
        raise JiraClientError("the Jira token file is not in `email:token` form")
    if path.stat().st_mode & 0o077:
        raise JiraClientError("the Jira token file must not be group or world accessible")
    return line


def request(
    path: str,
    credential: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    encoded = base64.b64encode(credential.encode("utf-8")).decode("ascii")
    req = urllib.request.Request(f"{JIRA_HOST}{path}", data=data, method=method)
    req.add_header("Authorization", f"Basic {encoded}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(NoRedirectHandler)
    try:
        with opener.open(req, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise JiraClientError(
            f"{method} {path} failed with HTTP {exc.code}: {detail}", status=exc.code
        ) from exc
    except urllib.error.URLError as exc:
        raise JiraClientError(f"{method} {path} could not reach Jira: {exc.reason}") from exc
    return json.loads(payload) if payload.strip() else None


def request_with_retry(
    path: str,
    credential: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> Any:
    try:
        return request(path, credential, method=method, body=body)
    except JiraClientError as exc:
        if exc.status != 429:
            raise
        time.sleep(1)
        return request(path, credential, method=method, body=body)
