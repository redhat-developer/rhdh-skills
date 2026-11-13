"""Normalized ticket model shared by every bug-triage step.

The scripts accept three Jira export shapes: the REST search envelope
(``{"issues": [...]}``), a bare list of REST issues, and the flatter records
returned by ``acli --json`` or a hand-built offline export. Normalization is
deliberately permissive about shape and strict about meaning: a field that is
absent stays absent, and the caller can always tell the difference between
"not fetched" and "empty".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_CURRENT_RELEASE = "2.1.0"
DEFAULT_AGED_DAYS = 90
DEFAULT_SAMPLE_SIZE = 12
DEFAULT_SEED = 18094

CUSTOMER_LABELS = ("RHDH-Customer",)
CUSTOMER_LINK_PREFIXES = ("RHDHSUPP", "ACCOUNT")
CUSTOMER_FIELD_NAMES = (
    "Customer Name",
    "Customers",
    "Customer Impact",
    "Case Link",
    "Support Case Reference",
    "SFDC cases",
)
# A support key anywhere in the ticket is a customer signal. It is deliberately
# narrow: a word such as "case" is ordinary English, but this key shape is not.
SUPPORT_KEY_RE = re.compile(r"\bRHDHSUPP-\d+\b")
PR_URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+/pull/\d+")
COMMIT_URL_RE = re.compile(
    r"https://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+/commit/([0-9a-fA-F]{7,40})"
)
JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")

DONE_CATEGORIES = {"done", "closed", "complete", "completed"}
DONE_STATUSES = {"closed", "done", "resolved", "released"}


def as_text(value: Any) -> str:
    """Flatten a Jira string, ADF document, or list into readable text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(part for part in (as_text(item) for item in value) if part)
    if isinstance(value, dict):
        # Atlassian Document Format: text nodes carry the sentence.
        if isinstance(value.get("text"), str):
            return value["text"]
        parts = []
        for key in ("content", "body", "value", "description", "comments"):
            if key in value:
                parts.append(as_text(value[key]))
        if parts:
            return "\n".join(part for part in parts if part)
        return ""
    return str(value)


def as_name(value: Any) -> str:
    """Return the human name of a Jira name/value object or scalar."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("name", "value", "displayName", "display_name", "key"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
            if isinstance(candidate, dict):
                nested = as_name(candidate)
                if nested:
                    return nested
        return ""
    if isinstance(value, list):
        return ", ".join(part for part in (as_name(item) for item in value) if part)
    return str(value)


def as_names(value: Any) -> List[str]:
    """Return one name per Jira value object, preserving order and dropping empties."""
    if value is None:
        return []
    if isinstance(value, list):
        return [name for name in (as_name(item) for item in value) if name]
    name = as_name(value)
    return [name] if name else []


def _payload(issue: Dict[str, Any]) -> Dict[str, Any]:
    fields = issue.get("fields")
    return fields if isinstance(fields, dict) else issue


def _first(payload: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, "", []):
            return payload[key]
    return None


def _comments(payload: Dict[str, Any]) -> List["Comment"]:
    raw = payload.get("comment")
    if raw is None:
        raw = payload.get("comments")
    if isinstance(raw, dict):
        raw = raw.get("comments")
    if not isinstance(raw, list):
        return []
    comments = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        author = as_name(item.get("author")) or as_name(item.get("updateAuthor"))
        comments.append(
            Comment(
                id=as_text(item.get("id")),
                author=author,
                body=as_text(item.get("body")),
                created=as_text(item.get("created")),
            )
        )
    return comments


def _links(payload: Dict[str, Any]) -> List["Link"]:
    raw = payload.get("issuelinks")
    if not isinstance(raw, list):
        return []
    links = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        link_type = as_name(item.get("type")) or "related"
        for direction, keys in (
            ("outward", ("outwardIssue", "outward_issue")),
            ("inward", ("inwardIssue", "inward_issue")),
        ):
            linked = next((item[key] for key in keys if isinstance(item.get(key), dict)), None)
            if not isinstance(linked, dict):
                continue
            linked_key = as_text(linked.get("key"))
            if not linked_key:
                continue
            fields = linked.get("fields") if isinstance(linked.get("fields"), dict) else {}
            links.append(
                Link(
                    type=link_type,
                    key=linked_key,
                    direction=direction,
                    summary=as_text(fields.get("summary")),
                    status=as_name(fields.get("status")),
                )
            )
    return links


def _collect_pr_urls(payload: Dict[str, Any], links: List["Link"]) -> List[str]:
    found = set(PR_URL_RE.findall(json.dumps(payload, default=str)))
    for link in links:
        found.update(PR_URL_RE.findall(link.summary))
    return sorted(found)


def _collect_commits(payload: Dict[str, Any]) -> List[str]:
    return sorted(set(COMMIT_URL_RE.findall(json.dumps(payload, default=str))))


def _customer_signals(
    ticket_key: str,
    payload: Dict[str, Any],
    labels: Iterable[str],
    links: List["Link"],
    field_names: Optional[Dict[str, str]],
) -> List[str]:
    signals: List[str] = []
    normalized_labels = {label.lower() for label in labels}
    for label in CUSTOMER_LABELS:
        if label.lower() in normalized_labels:
            signals.append(f"label:{label}")

    for link in links:
        prefix = link.key.split("-", 1)[0].upper()
        if prefix in CUSTOMER_LINK_PREFIXES:
            signals.append(f"link:{link.type}:{link.key}")

    # Field names arrive either as a customfield-id -> name map or inline as
    # human-readable keys. Both are checked; a mapped id is authoritative.
    for field_id, value in payload.items():
        field_name = ""
        if field_names and field_id in field_names:
            field_name = field_names[field_id]
        elif field_id in CUSTOMER_FIELD_NAMES:
            field_name = field_id
        if not field_name or field_name not in CUSTOMER_FIELD_NAMES:
            continue
        if as_text(value).strip():
            signals.append(f"field:{field_name}")

    text = json.dumps(payload, default=str)
    for key in sorted(set(SUPPORT_KEY_RE.findall(text))):
        if key != ticket_key:
            signals.append(f"text:{key}")
    return sorted(set(signals))


@dataclass
class Comment:
    author: str = ""
    body: str = ""
    created: str = ""
    id: str = ""


@dataclass
class Link:
    type: str = ""
    key: str = ""
    direction: str = ""
    summary: str = ""
    status: str = ""


@dataclass
class Ticket:
    key: str
    summary: str = ""
    description: str = ""
    status: str = ""
    status_category: str = ""
    resolution: str = ""
    created: str = ""
    updated: str = ""
    priority: str = ""
    issue_type: str = ""
    team: str = ""
    components: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    fix_versions: List[str] = field(default_factory=list)
    affects_versions: List[str] = field(default_factory=list)
    assignee: str = ""
    reporter: str = ""
    comments: List[Comment] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    pr_urls: List[str] = field(default_factory=list)
    commit_shas: List[str] = field(default_factory=list)
    customer_signals: List[str] = field(default_factory=list)
    is_done: bool = False
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)
    comments_complete: bool = False

    @property
    def search_text(self) -> str:
        return "\n".join(
            [self.summary, self.description, *[comment.body for comment in self.comments]]
        )


def normalize_issue(issue: Dict[str, Any], field_names: Optional[Dict[str, str]] = None) -> Ticket:
    """Convert one REST or flattened issue record into a Ticket."""
    if not isinstance(issue, dict):
        raise ValueError(f"issue must be an object, got {type(issue).__name__}")
    key = as_text(issue.get("key")) or as_text(issue.get("id"))
    if not key:
        raise ValueError("issue has no key")
    payload = _payload(issue)
    status = as_name(_first(payload, "status"))
    status_category = (
        as_name((payload.get("status") or {}).get("category"))
        if isinstance(payload.get("status"), dict)
        else ""
    )
    labels = as_names(payload.get("labels"))
    links = _links(payload)
    comments = _comments(payload)
    raw_comments = payload.get("comment", payload.get("comments"))
    comments_complete = (
        isinstance(raw_comments, list)
        and payload.get("commentsComplete") is True
        and len(comments) == len(raw_comments)
    ) or (
        isinstance(raw_comments, dict)
        and isinstance(raw_comments.get("comments"), list)
        and isinstance(raw_comments.get("total"), int)
        and raw_comments.get("startAt", 0) == 0
        and raw_comments["total"] == len(raw_comments["comments"])
        and len(comments) == len(raw_comments["comments"])
    )
    team = as_name(_first(payload, "customfield_10001", "team")) or ""
    components = as_names(payload.get("components"))
    is_done = bool(status_category.lower() in DONE_CATEGORIES or status.lower() in DONE_STATUSES)
    ticket = Ticket(
        key=key,
        summary=as_text(_first(payload, "summary")),
        description=as_text(_first(payload, "description")),
        status=status,
        status_category=status_category,
        resolution=as_name(_first(payload, "resolution")),
        created=as_text(_first(payload, "created")),
        updated=as_text(_first(payload, "updated")),
        priority=as_name(_first(payload, "priority")),
        issue_type=as_name(_first(payload, "issuetype", "issue_type")),
        team=team,
        components=components,
        labels=labels,
        fix_versions=as_names(_first(payload, "fixVersions", "fix_versions")),
        affects_versions=as_names(_first(payload, "versions", "affects_versions")),
        assignee=as_name(_first(payload, "assignee")),
        reporter=as_name(_first(payload, "reporter")),
        comments=comments,
        comments_complete=comments_complete,
        links=links,
        pr_urls=_collect_pr_urls(payload, links),
        commit_shas=_collect_commits(payload),
        is_done=is_done,
        raw=issue,
    )
    if ticket.assignee.lower() in ("unassigned", "none"):
        ticket.assignee = ""
    ticket.customer_signals = _customer_signals(
        ticket.key, payload, ticket.labels, ticket.links, field_names
    )
    return ticket


def extract_issues(document: Any) -> List[Dict[str, Any]]:
    """Return the issue list from every export shape the adapters accept."""
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    if isinstance(document, dict):
        for key in ("issues", "results", "items"):
            value = document.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError("export must be a list of issues or contain an 'issues' list")


def load_export(path: str, field_names: Optional[Dict[str, str]] = None) -> List[Ticket]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    mapped = field_names
    if isinstance(document, dict) and isinstance(document.get("fieldNames"), dict):
        mapped = {**document["fieldNames"], **(field_names or {})}
    return [normalize_issue(issue, mapped) for issue in extract_issues(document)]


def parse_datetime(value: str) -> Optional[datetime]:
    """Parse the ISO-8601 forms Jira emits, including the ``+0000`` offset."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Jira writes +0000; fromisoformat before 3.11 wants +00:00.
    if re.search(r"[+-]\d{4}$", text):
        text = text[:-5] + text[-5:-2] + ":" + text[-2:]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def age_days(created: str, as_of: Optional[datetime] = None) -> Optional[int]:
    created_at = parse_datetime(created)
    if created_at is None:
        return None
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0, (now - created_at).days)


def age_label(days: Optional[int]) -> str:
    if days is None:
        return "unknown age"
    if days < 180:
        return f"{days}d"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days / 365:.1f}y"
