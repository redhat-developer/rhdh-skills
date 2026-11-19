"""Read-only Jira adapters.

Two inputs are supported: a JSON export (the offline path used by tests and by a
host adapter) and ``acli``. Neither adapter can write, transition, comment, or
link anything. That is the structural half of the dry-run guarantee.
"""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from .model import (
    Ticket,
    extract_issues,
    merge_field_names,
    normalize_export,
    normalize_issue,
    validate_issue_key,
)


class JiraAdapterError(RuntimeError):
    """A read adapter failed; the caller reports it instead of guessing."""


def parse_acli_json(stdout: str, *, allow_partial: bool = False) -> List[Dict[str, Any]]:
    """Parse search envelopes, lists, and the single-object view response."""
    if not stdout.strip():
        raise JiraAdapterError("acli returned empty output instead of JSON")
    try:
        document = json.loads(stdout)
        issues = extract_issues(document, allow_partial=allow_partial)
        mapped = merge_field_names(
            document.get("names") if isinstance(document, dict) else None,
            document.get("fieldNames") if isinstance(document, dict) else None,
        )
        if mapped:
            return [
                {
                    **issue,
                    "fieldNames": merge_field_names(
                        mapped, issue.get("names"), issue.get("fieldNames")
                    ),
                }
                for issue in issues
            ]
        for issue in issues:
            merge_field_names(issue.get("names"), issue.get("fieldNames"))
    except ValueError as error:
        raise JiraAdapterError(f"acli returned invalid issue JSON: {error}") from error
    return issues


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
    except OSError as error:
        raise JiraAdapterError(f"acli could not run: {error}") from error
    if completed.returncode != 0 or completed.stderr.strip():
        message = (completed.stderr or completed.stdout or "").strip()
        raise JiraAdapterError(f"acli read failed (exit {completed.returncode}): {message}")
    return completed.stdout


def search_acli(
    jql: str,
    limit: Optional[int] = None,
    timeout: int = 180,
    fields: str = "key,summary",
) -> List[Dict[str, Any]]:
    """Run a read-only JQL search. ``limit`` caps rows; omit it to paginate.

    ``fields`` names the search-level fields to return; the deployment
    restricts which fields a search may return, so callers pass what the
    adapter allows (full reads are the complete path).
    """
    args = [
        "jira",
        "workitem",
        "search",
        "--jql",
        jql,
        "--fields",
        fields,
        "--json",
    ]
    if limit is None:
        args.append("--paginate")
    else:
        if limit < 1:
            raise JiraAdapterError("search limit must be positive")
        args.extend(["--limit", str(limit)])
    return parse_acli_json(_run_acli(args, timeout=timeout), allow_partial=limit is not None)


def view_acli(key: str, timeout: int = 60) -> Dict[str, Any]:
    try:
        validate_issue_key(key)
    except ValueError as error:
        raise JiraAdapterError(str(error)) from error
    issues = parse_acli_json(
        _run_acli(
            ["jira", "workitem", "view", key, "--fields", "*all", "--json"],
            timeout=timeout,
        )
    )
    if len(issues) != 1 or issues[0]["key"] != key:
        raise JiraAdapterError(f"acli did not return exactly the requested issue {key}")
    payload = issues[0].get("fields", issues[0])
    if any(field not in payload for field in ("summary", "status", "created")):
        raise JiraAdapterError(f"acli returned a partial full-issue read for {key}")
    return issues[0]


def _comments_acli(key: str) -> tuple[List[Dict[str, Any]], bool]:
    # This CLI supports --paginate for comment list (not just for search).
    stdout = _run_acli(
        ["jira", "workitem", "comment", "list", "--key", key, "--json", "--paginate"]
    )
    try:
        document = json.loads(stdout)
    except ValueError as error:
        raise JiraAdapterError(f"acli returned invalid comments JSON for {key}: {error}") from error
    complete = True
    if isinstance(document, list):
        comments = document
    elif isinstance(document, dict):
        if (
            document.get("error")
            or document.get("errors")
            or document.get("errorMessages")
            or document.get("success") is False
        ):
            raise JiraAdapterError(f"acli reported a failed comment read for {key}")
        comments = next(
            (
                document[name]
                for name in ("comments", "results", "items", "values")
                if isinstance(document.get(name), list)
            ),
            None,
        )
        total = document.get("total")
        complete = not (
            document.get("startAt", 0) != 0
            or ("total" in document and type(total) is not int)
            or (type(total) is int and comments is not None and total != len(comments))
            or document.get("isLast") is False
            or document.get("hasMore") is True
            or document.get("nextPageToken")
            or document.get("nextPage")
            or document.get("commentsComplete") is False
        )
    else:
        comments = None
    if not isinstance(comments, list) or any(
        not isinstance(comment, dict) or "body" not in comment for comment in comments
    ):
        raise JiraAdapterError(f"acli returned malformed comment records for {key}")
    return comments, complete


def _full_read(
    search_issue: Dict[str, Any], field_names: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    key = search_issue["key"]
    issue = view_acli(key)
    mapped = merge_field_names(
        field_names,
        search_issue.get("names"),
        search_issue.get("fieldNames"),
        issue.get("names"),
        issue.get("fieldNames"),
    )
    if mapped:
        issue = {**issue, "fieldNames": mapped}
    ticket = normalize_issue(issue)
    if not ticket.comments_complete:
        comments, complete = _comments_acli(key)
        payload = dict(issue.get("fields", issue))
        # Preserve customer references from the original page even if a later
        # comment read is incomplete. Prefer the fresh body for an existing id.
        original = payload.get("comment")
        if original is None:
            original = payload.get("comments")
        if isinstance(original, dict):
            original = original.get("comments")
        if isinstance(original, list):
            fresh_ids = {str(item["id"]) for item in comments if item.get("id")}
            extra = [
                item
                for item in original
                if (item.get("id") and str(item["id"]) not in fresh_ids)
                or (not item.get("id") and item not in comments)
            ]
            if extra:
                # The snapshots disagree, so keep the evidence but not a badge
                # of completeness, even if the newer command claimed success.
                comments += extra
                complete = False
        payload.pop("comment", None)
        payload["comments"] = comments
        payload["commentsComplete"] = complete
        issue = {**issue, "fields": payload} if "fields" in issue else payload
    return issue


def hydrate_acli(
    issue: Dict[str, Any], field_names: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Full read for a discovery hit, including available paginated comments."""
    return _full_read(issue, field_names)


def export_from_acli(
    jql: str, limit: Optional[int] = None, field_names: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Fetch a serializable export of full reads, or fail without partial success.

    The adapter owns no credentials. It only runs native read commands. Counts
    describe returned records, comment completeness, and coverage relative to
    the supplied deployment field catalogue. They do not imply that the catalogue
    is exhaustive, or that a limited search covers the whole backlog.
    """
    search_issues = search_acli(jql, limit=limit)
    keys = [issue["key"] for issue in search_issues]
    if len(set(keys)) != len(keys):
        raise JiraAdapterError("acli search returned duplicate issue keys")

    def read(issue):
        # Native reads can fail transiently. Retry once, never indefinitely or
        # as a success with omitted rows, and identify the failed issue.
        for attempt in range(2):
            try:
                return _full_read(issue, field_names)
            except JiraAdapterError as error:
                if attempt:
                    raise JiraAdapterError(
                        f"full read failed for {issue['key']}: {error}"
                    ) from error

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            issues = list(executor.map(read, search_issues))
        field_names = merge_field_names(field_names, *(issue.get("fieldNames") for issue in issues))
        tickets = normalize_export({"issues": issues, "fieldNames": field_names})
    except ValueError as error:
        raise JiraAdapterError(f"invalid full-issue read: {error}") from error
    return {
        "issues": issues,
        "fieldNames": field_names,
        "provenance": {
            "adapter": "acli",
            "jql": jql,
            "searchLimit": limit,
            "searchComplete": limit is None,
            "searchCount": len(search_issues),
            "fullReadCount": len(issues),
            "commentsFetchedCount": sum(ticket.comments_fetched for ticket in tickets),
            "commentsCompleteCount": sum(ticket.comments_complete for ticket in tickets),
            "customerFieldsCompleteCount": sum(
                ticket.customer_fields_complete for ticket in tickets
            ),
            "customerFieldCoverage": (
                "mapped-fields-complete"
                if tickets and all(ticket.customer_fields_complete for ticket in tickets)
                else "unknown"
            ),
        },
    }


def load_tickets_from_acli(
    jql: str, limit: Optional[int] = None, field_names: Optional[Dict[str, str]] = None
) -> List[Ticket]:
    return normalize_export(export_from_acli(jql, limit=limit, field_names=field_names))


# Search-level records carry the fields the deployment allows a search to
# return; the rest (chronology, links, fix versions, comments) needs full
# reads, which the corpus builder records per part instead of hiding.
CORPUS_SEARCH_FIELDS = "key,summary,description,status,labels,issuetype,assignee,priority,reporter"
CORPUS_SEARCH_GAPS = (
    "search-level records lack created, issuelinks, fixVersions, versions, "
    "resolution and comments; rank leads only, hydrate material candidates"
)


def build_corpus(
    search_jqls: List[str],
    full_jqls: List[str],
    field_names: Optional[Dict[str, str]] = None,
    as_of: str = "",
) -> Dict[str, Any]:
    """Build one merged open-and-closed corpus from bounded read-only parts.

    Search-level parts are fast and cover whole partitions; full-read parts
    carry chronology, links and fix versions where the fix-first route needs
    them. Every part's query, level and gaps are recorded; duplicate keys
    across parts are refused rather than silently merged.
    """
    issues: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}
    parts: List[Dict[str, Any]] = []
    merged_names = dict(field_names or {})
    for jql in search_jqls:
        records = search_acli(jql, fields=CORPUS_SEARCH_FIELDS)
        for record in records:
            key = record.get("key")
            if key in seen:
                raise JiraAdapterError(f"corpus parts overlap on {key}; use disjoint queries")
            seen[key] = "search-level"
            issues.append(record)
        parts.append(
            {
                "jql": jql,
                "level": "search-level",
                "count": len(records),
                "gaps": CORPUS_SEARCH_GAPS,
            }
        )
    for jql in full_jqls:
        document = export_from_acli(jql, field_names=field_names)
        for record in document["issues"]:
            key = record.get("key")
            if key in seen:
                raise JiraAdapterError(f"corpus parts overlap on {key}; use disjoint queries")
            seen[key] = "full-reads"
            issues.append(record)
        merged_names = merge_field_names(merged_names, document.get("fieldNames") or {})
        parts.append(
            {
                "jql": jql,
                "level": "full-reads",
                "count": len(document["issues"]),
                "adapter": "acli",
            }
        )
    return {
        "issues": issues,
        "fieldNames": merged_names,
        "provenance": {
            "asOf": as_of,
            "parts": parts,
            "coverage": (
                "bounded, explicitly queried partitions; not an exhaustive "
                "duplicate corpus unless a part's source proves otherwise"
            ),
        },
    }


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
