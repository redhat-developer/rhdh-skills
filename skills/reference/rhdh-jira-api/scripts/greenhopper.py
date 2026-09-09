#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""GET a Greenhopper sprint report using the local Jira token file.

acli has no sprint-report verb. This adapter reads the token file in-process
and never prints it. The agent must not cat the file, set AUTH, or call curl.

Usage:
  uv run scripts/greenhopper.py sprintreport --board 11374 --sprint 68649
  uv run scripts/greenhopper.py scopechange --board 11374 --sprint 68649

Token discovery: JIRA_TOKEN_FILE if set, otherwise `.jira-token` next to the
real acli binary. Format is one line `email:token`. A bare token 401s.
Optional JIRA_BASE_URL (default https://redhat.atlassian.net).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE = "https://redhat.atlassian.net"
SPRINTREPORT = "/rest/greenhopper/1.0/rapid/charts/sprintreport"
SCOPECHANGE = "/rest/greenhopper/1.0/rapid/charts/scopechangeburndownchart"


def _fail(message: str, *, status: int | None = None, code: int = 1) -> None:
    payload: dict[str, Any] = {"ok": False, "error": message}
    if status is not None:
        payload["status"] = status
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    raise SystemExit(code)


def find_token_file(acli_path: str | None = None) -> Path | None:
    """Return the token path if the file exists. Never read its contents."""
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


def load_email_token(acli_path: str | None = None) -> str:
    """Return the email:token line. Never print it."""
    path = find_token_file(acli_path)
    if path is None:
        _fail("Jira token file not found next to acli (or JIRA_TOKEN_FILE); skip Greenhopper")
    try:
        content = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError as exc:
        _fail(f"could not read Jira token file: {exc}")
    if ":" not in content:
        _fail("Jira token file is not email:token; a bare token 401s")
    return content


def greenhopper_get(path: str, *, timeout: float = 60.0) -> dict[str, Any]:
    base = os.environ.get("JIRA_BASE_URL", DEFAULT_BASE).rstrip("/")
    url = f"{base}{path}"
    encoded = base64.b64encode(load_email_token().encode()).decode()
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {encoded}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        _fail(f"Greenhopper HTTP {exc.code}", status=exc.code)
    except urllib.error.URLError as exc:
        _fail(f"Greenhopper request failed: {exc.reason}")
    except TimeoutError:
        _fail("Greenhopper request timed out")
    except json.JSONDecodeError as exc:
        _fail(f"Greenhopper body is not JSON: {exc}")
    if not isinstance(payload, dict):
        _fail("Greenhopper body is not a JSON object")
    return payload


def report_path(kind: str, board: int, sprint: int) -> str:
    endpoint = SPRINTREPORT if kind == "sprintreport" else SCOPECHANGE
    return f"{endpoint}?rapidViewId={board}&sprintId={sprint}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="GET a Greenhopper sprint report without printing credentials."
    )
    parser.add_argument(
        "kind",
        nargs="?",
        choices=("sprintreport", "scopechange"),
        default="sprintreport",
        help="Which Greenhopper chart to fetch (default sprintreport).",
    )
    parser.add_argument("--board", type=int, required=True, help="rapidViewId / board id")
    parser.add_argument("--sprint", type=int, required=True, help="sprintId")
    args = parser.parse_args(argv)
    report = greenhopper_get(report_path(args.kind, args.board, args.sprint))
    json.dump({"ok": True, "kind": args.kind, "report": report}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
