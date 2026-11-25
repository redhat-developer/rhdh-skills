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
from urllib.parse import urlsplit

DEFAULT_AGED_DAYS = 90
DEFAULT_SAMPLE_SIZE = 5
DEFAULT_SEED = 18094

CUSTOMER_LABELS = ("RHDH-Customer",)
CUSTOMER_LINK_PREFIXES = ("RHDHSUPP", "ACCOUNT")
CUSTOMER_FIELD_NAMES = (
    "Customer Name",
    "Customers",
    "Customer Impact",
    "Case Link",
    "Support Case Reference",
    "Account Number",
    "Account",
    "SFDC cases",
    "SFDC Cases Counter",
    "SFDC Cases Links",
    "SFDC Cases Open",
    "Customer Cloud Subscription (CCS)",
)
# A support key anywhere in the ticket is a customer signal. It is deliberately
# narrow: a word such as "case" is ordinary English, but this key shape is not.
SUPPORT_KEY_RE = re.compile(r"\b(?:RHDHSUPP|ACCOUNT)-\d+\b")
PR_URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+/pull/\d+")
COMMIT_URL_RE = re.compile(
    r"https://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+/commit/([0-9a-fA-F]{7,40})"
)
JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9_]*-\d+)\b")

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
        parts = []
        # Include ADF marks/attributes: the visible label can hide a support
        # reference or a PR URL. Jira custom-field options also use name/value.
        for key in (
            "text",
            "content",
            "body",
            "value",
            "name",
            "displayName",
            "display_name",
            "description",
            "comments",
            "url",
            "href",
            "key",
            "attrs",
            "marks",
        ):
            if key in value:
                parts.append(as_text(value[key]))
        if any(parts):
            return "\n".join(part for part in parts if part)
        return as_text(value.get("id"))
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
    if "fields" in issue and not isinstance(issue["fields"], dict):
        raise ValueError("issue fields must be an object")
    fields = issue.get("fields")
    return fields if isinstance(fields, dict) else issue


def validate_issue_key(key: Any) -> str:
    """Require a key, not an id or path fragment, before reads or file writes."""
    if not isinstance(key, str) or not JIRA_KEY_RE.fullmatch(key):
        raise ValueError(f"invalid issue key: {key!r}")
    return key


def _is_customer_field(name: str) -> bool:
    return name.casefold() in {
        item.casefold() for item in CUSTOMER_FIELD_NAMES
    } or name.casefold().startswith("sfdc cases")


def merge_field_names(*sources: Any) -> Dict[str, str]:
    """Merge REST names/export fieldNames without erasing a customer mapping.

    A deployment's field catalogue can be incomplete or inconsistent. A known
    customer alias wins a conflict; the mapping never certifies field coverage.
    """
    mapped: Dict[str, str] = {}
    for source in sources:
        if source is None:
            continue
        if not isinstance(source, dict) or any(
            not isinstance(key, str) or not isinstance(name, str) for key, name in source.items()
        ):
            raise ValueError("field names must map field ids to names")
        for key, name in source.items():
            if key not in mapped or not _is_customer_field(mapped[key]):
                mapped[key] = name
    return mapped


def _populated(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_populated(item) for item in value.values())
    if isinstance(value, list):
        return any(_populated(item) for item in value)
    return value not in (None, "", 0, False, "0") and bool(as_text(value).strip())


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
        if not isinstance(item, dict) or "body" not in item:
            raise ValueError("comment records must be objects with a body")
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
        link_type = as_name(_first(item, "type", "linktype")) or "related"
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
        if prefix in CUSTOMER_LINK_PREFIXES or link.type.strip().casefold() == "account":
            signals.append(f"link:{link.type}:{link.key}")

    # Field names arrive either as a customfield-id -> name map or inline as
    # human-readable keys. Neither a known name nor an id mapping may erase a
    # customer signal found through the other spelling.
    for field_id, value in payload.items():
        field_name = ""
        if _is_customer_field(field_id):
            field_name = field_id
        elif field_names and field_id in field_names:
            field_name = field_names[field_id]
        if not field_name or not _is_customer_field(field_name):
            continue
        if _populated(value):
            signals.append(f"field:{field_name}")

    text = json.dumps(payload, default=str)
    for key in sorted(set(SUPPORT_KEY_RE.findall(text))):
        if key != ticket_key:
            signals.append(f"text:{key}")
    return sorted(set(signals))


def _host_customer_signals(issue: Dict[str, Any], payload: Dict[str, Any]) -> List[str]:
    """Accept cited host review, never a generic customer-word text heuristic.

    triageCustomerSignals is additive enrichment, not a native source fact or
    evidence that missing fields were fetched. The host owns semantic review of
    the cited material; normalization validates the declaration's structure.
    """
    signals = []
    for source in [issue] if issue is payload else [issue, payload]:
        if "triageCustomerSignals" not in source:
            continue
        declarations = source["triageCustomerSignals"]
        if not isinstance(declarations, list):
            raise ValueError("triageCustomerSignals must be a list of cited reasons")
        for declaration in declarations:
            if not isinstance(declaration, dict):
                raise ValueError("triageCustomerSignals records need a ref and reason")
            ref, reason = declaration.get("ref"), declaration.get("reason")
            if not isinstance(ref, str) or not isinstance(reason, str) or not reason.strip():
                raise ValueError("triageCustomerSignals records need a nonempty ref and reason")
            valid = bool(JIRA_KEY_RE.fullmatch(ref))
            if not valid:
                try:
                    url = urlsplit(ref)
                    valid = bool(
                        url.scheme == "https"
                        and url.hostname
                        and not url.username
                        and not url.password
                        and not re.search(r"[\s\x00-\x1f\x7f<>]", ref)
                    )
                    # Accessing port also validates a malformed URL port.
                    if url.port is not None and not 0 < url.port <= 65535:
                        valid = False
                except ValueError:
                    valid = False
            if not valid:
                raise ValueError("triageCustomerSignals ref must be a valid HTTPS URL or Jira key")
            signals.append(f"host:{ref}:{' '.join(reason.split())}")
    return signals


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
    reporter_account_id: str = ""
    comments: List[Comment] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    pr_urls: List[str] = field(default_factory=list)
    commit_shas: List[str] = field(default_factory=list)
    customer_signals: List[str] = field(default_factory=list)
    is_done: bool = False
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)
    comments_complete: bool = False
    comments_fetched: bool = False
    customer_fields_read: List[str] = field(default_factory=list)
    unmapped_custom_fields: List[str] = field(default_factory=list)
    read_gaps: List[str] = field(default_factory=list)
    affects_versions_ambiguous: bool = False
    customer_fields_complete: bool = False
    former_keys: List[str] = field(default_factory=list)

    @property
    def search_text(self) -> str:
        return "\n".join(
            [self.summary, self.description, *[comment.body for comment in self.comments]]
        )


def _former_keys(issue: Dict[str, Any], payload: Dict[str, Any], key: str) -> List[str]:
    aliases = as_names(_first(payload, "formerKeys", "former_keys"))
    changelog = issue.get("changelog", {})
    histories = changelog.get("histories", []) if isinstance(changelog, dict) else []
    for history in histories:
        for item in history.get("items", []) if isinstance(history, dict) else []:
            if isinstance(item, dict) and str(item.get("field", "")).casefold() == "key":
                aliases.extend([item.get("fromString"), item.get("toString")])
    return sorted(
        {
            value
            for value in aliases
            if isinstance(value, str) and JIRA_KEY_RE.fullmatch(value) and value != key
        }
    )


def normalize_issue(issue: Dict[str, Any], field_names: Optional[Dict[str, str]] = None) -> Ticket:
    """Convert one REST or flattened issue record into a Ticket."""
    if not isinstance(issue, dict):
        raise ValueError(f"issue must be an object, got {type(issue).__name__}")
    key = validate_issue_key(issue.get("key"))
    payload = _payload(issue)
    field_names = merge_field_names(field_names, issue.get("names"), issue.get("fieldNames"))
    status = as_name(_first(payload, "status"))
    status_category = (
        as_name(_first(payload["status"], "statusCategory", "category"))
        if isinstance(payload.get("status"), dict)
        else as_name(_first(payload, "statusCategory", "status_category"))
    )
    labels = as_names(payload.get("labels"))
    links = _links(payload)
    comments = _comments(payload)
    raw_comments = payload.get("comment")
    if raw_comments is None:
        raw_comments = payload.get("comments")
    comments_fetched = isinstance(raw_comments, list) or (
        isinstance(raw_comments, dict) and isinstance(raw_comments.get("comments"), list)
    )
    comments_complete = (
        isinstance(raw_comments, list)
        and payload.get("commentsComplete") is True
        and len(comments) == len(raw_comments)
    ) or (
        isinstance(raw_comments, dict)
        and isinstance(raw_comments.get("comments"), list)
        and type(raw_comments.get("total")) is int
        and raw_comments.get("startAt", 0) == 0
        and raw_comments["total"] == len(raw_comments["comments"])
        and len(comments) == len(raw_comments["comments"])
    )
    # An explicit incomplete marker must win even over apparently matching totals.
    if payload.get("commentsComplete") is False or (
        isinstance(raw_comments, dict)
        and (
            raw_comments.get("commentsComplete") is False
            or raw_comments.get("isLast") is False
            or raw_comments.get("hasMore") is True
            or raw_comments.get("nextPageToken")
            or raw_comments.get("nextPage")
        )
    ):
        comments_complete = False
    team = as_name(_first(payload, "customfield_10001", "team")) or ""
    components = as_names(payload.get("components"))
    raw_versions = _first(payload, "versions", "affects_versions")
    version_items = raw_versions if isinstance(raw_versions, list) else [raw_versions]
    versions_ambiguous = raw_versions is not None and any(
        not isinstance(value, (str, dict)) or not as_name(value).strip() for value in version_items
    )
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
        affects_versions=as_names(raw_versions),
        affects_versions_ambiguous=versions_ambiguous,
        assignee=as_name(_first(payload, "assignee")),
        reporter=as_name(_first(payload, "reporter")),
        reporter_account_id=as_text(payload["reporter"].get("accountId"))
        if isinstance(payload.get("reporter"), dict)
        else "",
        comments=comments,
        comments_complete=comments_complete,
        comments_fetched=comments_fetched,
        links=links,
        pr_urls=_collect_pr_urls(payload, links),
        commit_shas=_collect_commits(payload),
        is_done=is_done,
        raw=issue,
        former_keys=_former_keys(issue, payload, key),
    )
    if ticket.assignee.lower() in ("unassigned", "none"):
        ticket.assignee = ""
    ticket.customer_signals = sorted(
        set(
            _customer_signals(ticket.key, payload, ticket.labels, ticket.links, field_names)
            + _host_customer_signals(issue, payload)
        )
    )
    ticket.customer_fields_read = sorted(
        {
            field_id if _is_customer_field(field_id) else field_names[field_id]
            for field_id in payload
            if _is_customer_field(field_id) or _is_customer_field(field_names.get(field_id, ""))
        }
    )
    ticket.unmapped_custom_fields = sorted(
        field_id
        for field_id in payload
        if field_id.startswith("customfield_") and field_id not in field_names
    )
    # Coverage is relative to the supplied field catalogue, never to hardcoded
    # tenant ids or to a customerFieldsComplete claim in an arbitrary export.
    # A nonempty catalogue plus actual field presence is required; null values
    # mean fetched-and-empty, while missing keys mean not read.
    customer_field_ids = {
        field_id
        for field_id, name in field_names.items()
        if field_id.startswith("customfield_") and _is_customer_field(name)
    }
    raw_labels = payload.get("labels")
    raw_links = payload.get("issuelinks")
    ticket.customer_fields_complete = bool(
        customer_field_ids
        and customer_field_ids <= payload.keys()
        and isinstance(raw_labels, list)
        and all(isinstance(label, str) for label in raw_labels)
        and isinstance(raw_links, list)
        and all(isinstance(link, dict) for link in raw_links)
        and len(links) >= len(raw_links)
    )
    if not ticket.customer_fields_complete:
        ticket.read_gaps.append("customer-field coverage is not established by this export")
        missing = sorted(customer_field_ids - payload.keys())
        if missing:
            ticket.read_gaps.append("mapped customer fields not fetched: " + ", ".join(missing))
    if ticket.unmapped_custom_fields:
        ticket.read_gaps.append(
            "unmapped custom fields: " + ", ".join(ticket.unmapped_custom_fields)
        )
    if not comments_fetched:
        ticket.read_gaps.append("comment history was not fetched")
    elif not comments_complete:
        ticket.read_gaps.append("comment history was fetched but completeness is unverified")
    return ticket


def extract_issues(document: Any, *, allow_partial: bool = False) -> List[Dict[str, Any]]:
    """Return the issue list from every export shape the adapters accept."""
    records = None
    if isinstance(document, list):
        records = document
    elif isinstance(document, dict):
        if (
            document.get("error")
            or document.get("errors")
            or document.get("errorMessages")
            or document.get("success") is False
        ):
            raise ValueError("export reports a failed Jira read")
        for key in ("issues", "results", "items"):
            if key in document:
                if not isinstance(document[key], list):
                    raise ValueError(f"export {key} must be a list")
                records = document[key]
                break
        if records is None and "key" in document:
            records = [document]
        if records is not None and "key" not in document:
            for name in ("total", "startAt"):
                if name in document and (type(document[name]) is not int or document[name] < 0):
                    raise ValueError(f"export {name} must be a nonnegative integer")
        if records is not None and "key" not in document and not allow_partial:
            total = document.get("total")
            if (
                (type(total) is int and total != len(records))
                or document.get("startAt", 0) != 0
                or document.get("isLast") is False
                or document.get("hasMore") is True
                or document.get("nextPageToken")
                or document.get("nextPage")
            ):
                raise ValueError("export contains a partial issue list")
    if records is None:
        raise ValueError("export must be an issue object, a list, or contain an 'issues' list")
    keys = set()
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            raise ValueError(f"issue record {index} must be an object")
        if (
            item.get("error")
            or item.get("errors")
            or item.get("errorMessages")
            or item.get("success") is False
        ):
            raise ValueError(f"issue record {index} reports a failed Jira read")
        key = validate_issue_key(item.get("key"))
        if key in keys:
            raise ValueError(f"duplicate issue key in export: {key}")
        keys.add(key)
        _payload(item)
    return records


def normalize_export(document: Any, field_names: Optional[Dict[str, str]] = None) -> List[Ticket]:
    mapped = merge_field_names(
        document.get("names") if isinstance(document, dict) else None,
        document.get("fieldNames") if isinstance(document, dict) else None,
        field_names,
    )
    return [normalize_issue(issue, mapped) for issue in extract_issues(document)]


def load_export(path: str, field_names: Optional[Dict[str, str]] = None) -> List[Ticket]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    return normalize_export(document, field_names)


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
