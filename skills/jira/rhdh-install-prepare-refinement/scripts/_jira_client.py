"""Minimal Jira REST client for JQL search (stdlib only)."""

from __future__ import annotations

import json
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


def search_jql(auth: JiraAuth, jql: str, *, max_results: int = 100) -> list[dict]:
    """Paginated issue search via /rest/api/3/search/jql (CHANGE-2046)."""
    issues: list[dict] = []
    next_token: str | None = None
    page_size = min(50, max_results)

    while len(issues) < max_results:
        payload: dict[str, Any] = {
            "jql": jql,
            "maxResults": page_size,
            "fields": SEARCH_FIELDS,
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


def child_count(auth: JiraAuth, parent_key: str) -> int:
    jql = f'parent = {parent_key} AND status != Closed'
    data = _request(
        auth,
        "POST",
        "/rest/api/3/search/approximate-count",
        {"jql": jql},
    )
    return int(data.get("count", 0))
