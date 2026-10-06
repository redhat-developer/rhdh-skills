"""Jira JQL search via REST (API token) or acli (OAuth / keyring token)."""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from typing import Any

from _auth import JiraAuth

SEARCH_FIELDS = [
    "summary",
    "status",
    "issuetype",
    "assignee",
    "priority",
    "parent",
    "customfield_10028",
]

SEARCH_JQL_PATH = "/rest/api/3/search/jql"

# acli rejects customfield_* in --fields
ACLI_SEARCH_FIELDS = "key,summary,status,issuetype,assignee,priority"


def _request(auth: JiraAuth, method: str, path: str, body: dict | None = None) -> Any:
    url = f"{auth.server}{path}"
    data = None
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    password = f"{auth.login}:{auth.token}".encode("utf-8")
    import base64

    req.add_header("Authorization", "Basic " + base64.b64encode(password).decode("ascii"))
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Jira API {exc.code} for {path}: {detail[:500]}") from exc


def _acli_run(args: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["acli", "jira", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "acli failed").strip()
        raise SystemExit(f"acli jira failed: {detail[:500]}")
    return result


def search_jql(
    auth: JiraAuth,
    jql: str,
    *,
    max_results: int = 100,
    fields: list[str] | None = None,
) -> list[dict]:
    if auth.via_acli:
        return _acli_search(jql, max_results=max_results, fields=fields)

    issues: list[dict] = []
    next_token: str | None = None
    page_size = min(50, max_results)

    while len(issues) < max_results:
        payload: dict[str, Any] = {
            "jql": jql,
            "maxResults": page_size,
            "fields": fields or SEARCH_FIELDS,
            "fieldsByKeys": True,
        }
        if next_token:
            payload["nextPageToken"] = next_token

        data = _request(auth, "POST", SEARCH_JQL_PATH, payload)
        batch = data.get("issues", [])
        issues.extend(batch)

        if data.get("isLast", True) or not batch:
            break
        next_token = data.get("nextPageToken")
        if not next_token:
            break

    return issues[:max_results]


def _acli_search(jql: str, *, max_results: int, fields: list[str] | None) -> list[dict]:
    args = [
        "workitem",
        "search",
        "--jql",
        jql,
        "--json",
        "--limit",
        str(max_results),
        "--fields",
        ACLI_SEARCH_FIELDS,
    ]
    raw = json.loads(_acli_run(args).stdout)
    if isinstance(raw, dict):
        return raw.get("issues", raw.get("values", []))
    return raw


def child_count(auth: JiraAuth, parent_key: str) -> int:
    jql = f'parent = {parent_key} AND status != Closed'
    if auth.via_acli:
        out = _acli_run(["workitem", "search", "--jql", jql, "--count"]).stdout
        for line in reversed(out.strip().splitlines()):
            digits = "".join(c for c in line if c.isdigit())
            if digits:
                return int(digits)
        return 0
    data = _request(
        auth,
        "POST",
        "/rest/api/3/search/approximate-count",
        {"jql": jql},
    )
    return int(data.get("count", 0))
