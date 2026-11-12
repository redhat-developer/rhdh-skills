"""Read-only GitHub evidence for fix verification.

``gh pr view`` and ``gh search prs`` are reads. No adapter here can comment,
merge, label, or push. A cache file makes the same evidence reproducible offline.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List, Optional

from .duplicates import distinctive_phrases
from .model import JIRA_KEY_RE, Ticket

DEFAULT_REPOS = (
    "redhat-developer/rhdh",
    "redhat-developer/rhdh-operator",
    "redhat-developer/rhdh-plugins",
    "redhat-developer/community-plugins",
)

PR_FIELDS = "number,title,state,mergedAt,mergeCommit,baseRefName,url,closedAt"

# Searching every key a bug mentions would turn one collection pass into many
# forge calls; the first few cover the linked-ticket case in practice.
MAX_LINKED_KEYS = 5


class ForgeAdapterError(RuntimeError):
    """A read adapter failed; the caller records it as missing evidence."""


def load_cache(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ForgeAdapterError("forge cache must be an object")
    pulls = document.get("pulls", document)
    return pulls if isinstance(pulls, dict) else {}


def _run_gh(args: List[str], timeout: int = 30) -> str:
    try:
        completed = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as error:
        raise ForgeAdapterError("gh is not on PATH") from error
    except subprocess.TimeoutExpired as error:
        raise ForgeAdapterError(f"gh timed out after {timeout}s") from error
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise ForgeAdapterError(f"gh failed: {message}")
    return completed.stdout


def normalize_pr(payload: Dict[str, Any], url: str = "") -> Dict[str, Any]:
    merged_at = payload.get("mergedAt") or payload.get("merged_at") or ""
    state = str(payload.get("state") or "").upper()
    merge_commit = payload.get("mergeCommit")
    if isinstance(merge_commit, dict):
        merge_commit = merge_commit.get("oid") or merge_commit.get("sha") or ""
    repository = payload.get("repository")
    if isinstance(repository, dict):
        repository = repository.get("nameWithOwner") or repository.get("name") or ""
    elif not isinstance(repository, str):
        repository = ""
    return {
        "url": payload.get("url") or url,
        "number": payload.get("number"),
        "title": payload.get("title") or "",
        "state": state,
        "merged": bool(merged_at) or state == "MERGED",
        "mergedAt": merged_at,
        "mergeCommit": merge_commit or "",
        "baseRefName": payload.get("baseRefName") or payload.get("base_ref_name") or "",
        "repository": repository,
    }


def lookup_pr(url: str, cache: Dict[str, Any], use_gh: bool) -> Dict[str, Any]:
    cached = cache.get(url)
    if isinstance(cached, dict):
        return normalize_pr(cached, url)
    if not use_gh:
        return {
            "url": url,
            "state": "UNKNOWN",
            "merged": False,
            "mergedAt": "",
            "mergeCommit": "",
            "baseRefName": "",
            "title": "",
            "source": "not-fetched",
        }
    try:
        output = _run_gh(["pr", "view", url, "--json", PR_FIELDS])
    except ForgeAdapterError as error:
        return {
            "url": url,
            "state": "UNKNOWN",
            "merged": False,
            "mergedAt": "",
            "mergeCommit": "",
            "baseRefName": "",
            "title": "",
            "source": "error",
            "error": str(error),
        }
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        return {
            "url": url,
            "state": "UNKNOWN",
            "merged": False,
            "mergedAt": "",
            "mergeCommit": "",
            "baseRefName": "",
            "title": "",
            "source": "error",
            "error": f"invalid gh JSON: {error}",
        }
    result = normalize_pr(payload, url)
    result["source"] = "gh"
    return result


def search_prs_for_key(
    key: str,
    cache: Dict[str, Any],
    use_gh: bool,
    repos: Optional[List[str]] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Return PRs that mention a Jira key, or an empty list when live search is off."""
    if not use_gh:
        return [
            item
            for item in cache.values()
            if isinstance(item, dict) and key in json.dumps(item, default=str)
        ]
    results: List[Dict[str, Any]] = []
    seen = set()
    for repo in repos or list(DEFAULT_REPOS):
        args = [
            "search",
            "prs",
            key,
            "--repo",
            repo,
            "--limit",
            str(limit),
            "--json",
            "number,title,state,url,repository,closedAt",
        ]
        try:
            payload = json.loads(_run_gh(args))
        except (ForgeAdapterError, json.JSONDecodeError):
            continue
        for item in payload if isinstance(payload, list) else []:
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            normalized = normalize_pr(item, url)
            normalized["source"] = "gh-search"
            results.append(normalized)
    return results


def collect_for_ticket(
    ticket: Ticket,
    cache: Dict[str, Any],
    use_gh: bool,
) -> Dict[str, Any]:
    pulls = [lookup_pr(url, cache, use_gh) for url in ticket.pr_urls]
    jira_keys = sorted(
        {match for match in JIRA_KEY_RE.findall(ticket.search_text) if match != ticket.key}
        | {link.key for link in ticket.links if link.key and link.key != ticket.key}
    )
    known = {pull.get("url") for pull in pulls}

    def add(found: List[Dict[str, Any]], via: str) -> None:
        for pull in found:
            url = pull.get("url")
            if not url or url in known:
                continue
            known.add(url)
            pulls.append({**pull, "foundVia": via})

    add(search_prs_for_key(ticket.key, cache, use_gh), ticket.key)
    # A fix can land under another bug's key while this ticket stays open. The
    # linked keys are where that shows up, so search them too.
    for linked_key in jira_keys[:MAX_LINKED_KEYS]:
        add(search_prs_for_key(linked_key, cache, use_gh), linked_key)
    return {
        "key": ticket.key,
        "summary": ticket.summary,
        "pullRequests": pulls,
        "linkedJiraKeys": jira_keys,
        "searchPhrases": distinctive_phrases(ticket),
        "fixVersionFields": ticket.fix_versions,
        "affectsVersionFields": ticket.affects_versions,
        "hasDescription": bool(ticket.description.strip()),
        "hasComments": bool(ticket.comments),
        "linkedJira": [
            {
                "key": link.key,
                "type": link.type,
                "direction": link.direction,
                "summary": link.summary,
                "status": link.status,
            }
            for link in ticket.links
        ],
        "customerSignals": ticket.customer_signals,
    }
