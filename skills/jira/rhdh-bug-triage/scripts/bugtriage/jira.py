"""Read-only Jira adapters.

Two inputs are supported: a JSON export (the offline path used by tests and by a
host adapter) and ``acli``. Neither adapter can write, transition, comment, or
link anything. That is the structural half of the dry-run guarantee.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List, Optional

from .model import Ticket, normalize_issue


class JiraAdapterError(RuntimeError):
    """A read adapter failed; the caller reports it instead of guessing."""


def parse_acli_json(stdout: str) -> List[Dict[str, Any]]:
    """Parse the two JSON shapes ``acli`` emits: a list or a wrapper object."""
    if not stdout.strip():
        return []
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise JiraAdapterError(f"acli returned invalid JSON: {error}") from error
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    if isinstance(document, dict):
        for key in ("issues", "results", "items"):
            if isinstance(document.get(key), list):
                return [item for item in document[key] if isinstance(item, dict)]
    raise JiraAdapterError("acli returned JSON without an issue list")


def _run_acli(args: List[str], timeout: int = 120) -> str:
    try:
        completed = subprocess.run(
            ["acli", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        raise JiraAdapterError(
            "acli is not on PATH; install it and run /setup-rhdh-skills jira"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise JiraAdapterError(f"acli timed out after {timeout}s") from error
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise JiraAdapterError(f"acli failed: {message}")
    return completed.stdout


def search_acli(jql: str, limit: Optional[int] = None, timeout: int = 180) -> List[Dict[str, Any]]:
    """Run a read-only JQL search. ``limit`` caps rows; omit it to paginate."""
    args = [
        "jira",
        "workitem",
        "search",
        "--jql",
        jql,
        "--fields",
        "*all",
        "--json",
    ]
    if limit is None:
        args.append("--paginate")
    else:
        args.extend(["--limit", str(limit)])
    return parse_acli_json(_run_acli(args, timeout=timeout))


def view_acli(key: str, timeout: int = 60) -> Dict[str, Any]:
    issues = parse_acli_json(
        _run_acli(
            ["jira", "workitem", "view", key, "--fields", "*all", "--json"],
            timeout=timeout,
        )
    )
    if not issues:
        raise JiraAdapterError(f"acli returned no issue for {key}")
    return issues[0]


def load_tickets_from_acli(jql: str, limit: Optional[int] = None) -> List[Ticket]:
    return [normalize_issue(issue) for issue in search_acli(jql, limit=limit)]


def write_acli_probe() -> Dict[str, Any]:
    """Report whether acli is installed and whether a read smoke check passes."""
    report: Dict[str, Any] = {"installed": False, "readable": False, "detail": ""}
    try:
        version = subprocess.run(
            ["acli", "--version"], capture_output=True, text=True, timeout=10, check=False
        )
        report["installed"] = version.returncode == 0
        report["version"] = version.stdout.strip() or version.stderr.strip()
    except (FileNotFoundError, subprocess.SubprocessError) as error:
        report["detail"] = str(error)
        return report
    try:
        _run_acli(["jira", "project", "list", "--recent", "1"], timeout=20)
        report["readable"] = True
    except JiraAdapterError as error:
        report["detail"] = str(error)
    return report
