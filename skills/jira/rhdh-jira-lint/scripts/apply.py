#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Apply a hardened Jira lint remediation plan.

The plan is schema 2. It carries the scanner result, the evidence behind every
decision, and the exact field writes that are authorized. Comments are derived
from successful writes; they are never supplied as a separate free-form list.

Usage:
  uv run scripts/apply.py --plan /tmp/lint-plan.json --dry-run
  uv run scripts/apply.py --plan /tmp/lint-plan.json --confirm --receipt /tmp/lint-receipt.json

Token discovery: JIRA_TOKEN_FILE, else `.jira-token` next to acli. The Jira host
is fixed to the Red Hat instance; arbitrary base URLs are not accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from jira_client import (  # noqa: E402
    JIRA_HOST,
    JiraClientError,
)
from jira_client import (  # noqa: E402
    load_email_token as load_jira_email_token,
)
from jira_client import (  # noqa: E402
    request_with_retry as jira_request_with_retry,
)

COMMENT_MARKER = "[rhdh-jira-lint]"
COMMENT_VISIBILITY = {"type": "group", "value": "Red Hat Employee"}
PROJECTS = ("RHIDP", "RHDHPLAN", "RHDHBUGS")
EXCLUDED_STATUSES = ("Closed", "Release Pending")
EXCLUDED_TYPES = ("Outcome",)
PRIORITIES_DIRECT = {"Normal", "Major", "Minor"}
PRIORITIES_INHERITED = {"Blocker", "Critical"}
POINTS = {1, 2, 3, 5, 8}
SIZES = {"XS", "S", "M", "L", "XL"}
RULES = {
    "LINT-COMPONENT",
    "LINT-PRIORITY",
    "LINT-POINTS",
    "LINT-SIZE",
    "LINT-FIXVERSION-MULTI",
    "LINT-FF-PRIORITY",
    "LINT-CF-PRIORITY",
    "LINT-GA-OPEN",
    "LINT-RN-TYPE",
    "LINT-RN-TEXT",
    "LINT-RN-STATUS",
}
WRITE_RULES = {
    "LINT-COMPONENT": "components",
    "LINT-PRIORITY": "priority",
    "LINT-POINTS": "story_points",
    "LINT-SIZE": "size",
    "LINT-FIXVERSION-MULTI": "fixVersions",
    "LINT-RN-TYPE": "rn_type",
    "LINT-RN-TEXT": "rn_text",
    "LINT-RN-STATUS": "rn_status",
}
DECISIONS = {"supported", "insufficient", "human_required", "waived"}
ACTIONS = {
    "derive",
    "estimate",
    "classify",
    "draft",
    "escalate",
    "choose",
    "review-waiver",
}
PLAN_KEYS = {"schema", "run_id", "scan_digest", "scope", "fields", "issues"}
ISSUE_KEYS = {
    "key",
    "summary",
    "project",
    "issuetype",
    "status",
    "labels",
    "expected_updated",
    "mention",
    "findings",
}
FINDING_KEYS = {
    "rule",
    "action",
    "decision",
    "evidence",
    "set",
    "precondition",
    "reason",
}


class ApplyError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: int = 4):
        super().__init__(message)
        self.status = status
        self.code = code


class FatalRunError(RuntimeError):
    pass


def load_email_token() -> str:
    try:
        return load_jira_email_token()
    except JiraClientError as exc:
        raise ApplyError(str(exc), code=3) from exc


def request_with_retry(
    path: str,
    credential: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> Any:
    try:
        return jira_request_with_retry(path, credential, method=method, body=body)
    except JiraClientError as exc:
        raise ApplyError(str(exc), status=exc.status) from exc


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def plan_hash(plan: dict[str, Any]) -> str:
    return digest(plan)


def _text(node: Any) -> str:
    if isinstance(node, list):
        return " ".join(_text(item) for item in node)
    if not isinstance(node, dict):
        return str(node) if node is not None else ""
    if node.get("type") == "text":
        return str(node.get("text") or "")
    if node.get("type") == "mention":
        return str((node.get("attrs") or {}).get("text") or "")
    return " ".join(_text(child) for child in node.get("content") or [])


def is_adf(value: Any) -> bool:
    return isinstance(value, dict) and value.get("type") == "doc"


def adf_nonempty(value: Any) -> bool:
    return is_adf(value) and bool(_text(value).strip())


def normalize(value: Any) -> Any:
    if isinstance(value, dict):
        if "value" in value:
            return normalize(value["value"])
        if "name" in value:
            return value["name"]
        if is_adf(value):
            return " ".join(_text(value).split())
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return sorted(str(normalize(item)) for item in value)
    return value


def values_match(expected: Any, actual: Any) -> bool:
    if is_adf(expected):
        return " ".join(_text(expected).split()) == " ".join(_text(actual).split())
    return normalize(expected) == normalize(actual)


def has_value(raw: Any) -> bool:
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    if isinstance(raw, str):
        return bool(raw.strip())
    if isinstance(raw, dict):
        if "value" in raw:
            return has_value(raw["value"])
        if "name" in raw:
            return has_value(raw["name"])
        return any(has_value(value) for value in raw.values())
    if isinstance(raw, list):
        return any(has_value(item) for item in raw)
    return bool(str(raw).strip())


def _issue_key(key: Any) -> bool:
    return isinstance(key, str) and bool(re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", key))


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_keys(obj: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(obj) - allowed
    if unknown:
        raise ApplyError(f"{label}: unknown keys {sorted(unknown)}", code=2)


def _validate_evidence(rule: str, evidence: Any, decision: str) -> None:
    if not isinstance(evidence, dict) or not evidence:
        raise ApplyError(f"{rule}: evidence must be a non-empty object", code=2)
    if not _nonempty_str(evidence.get("basis")):
        raise ApplyError(f"{rule}: evidence.basis must be a non-empty string", code=2)
    if decision != "supported":
        return
    if rule == "LINT-POINTS":
        if not isinstance(evidence.get("acceptance_criteria"), int):
            raise ApplyError("LINT-POINTS: evidence.acceptance_criteria must be an integer", code=2)
        if not isinstance(evidence.get("affected_areas"), list) or not evidence["affected_areas"]:
            raise ApplyError(
                "LINT-POINTS: evidence.affected_areas must be a non-empty list", code=2
            )
    if rule == "LINT-SIZE":
        if not isinstance(evidence.get("scope_signals"), list) or not evidence["scope_signals"]:
            raise ApplyError("LINT-SIZE: evidence.scope_signals must be a non-empty list", code=2)
    if rule == "LINT-FIXVERSION-MULTI":
        if not _nonempty_str(evidence.get("chosen_version")):
            raise ApplyError("LINT-FIXVERSION-MULTI: evidence.chosen_version is required", code=2)
        if not isinstance(evidence.get("current_versions"), list):
            raise ApplyError(
                "LINT-FIXVERSION-MULTI: evidence.current_versions must be a list", code=2
            )
    if rule == "LINT-RN-TYPE":
        if not _nonempty_str(evidence.get("component")):
            raise ApplyError("LINT-RN-TYPE: evidence.component is required", code=2)
    if rule == "LINT-RN-TEXT":
        if not _nonempty_str(evidence.get("summary")):
            raise ApplyError("LINT-RN-TEXT: evidence.summary is required", code=2)
        if not _nonempty_str(evidence.get("outcome")):
            raise ApplyError("LINT-RN-TEXT: evidence.outcome is required", code=2)
    if rule == "LINT-RN-STATUS":
        if not _nonempty_str(evidence.get("rn_type")):
            raise ApplyError("LINT-RN-STATUS: evidence.rn_type is required", code=2)


def _validate_value(
    rule: str,
    field: str,
    value: Any,
    evidence: dict[str, Any],
    *,
    revert: bool = False,
) -> None:
    if rule == "LINT-COMPONENT":
        if not isinstance(value, list) or (not value and not revert):
            raise ApplyError("LINT-COMPONENT: components must be a non-empty list", code=2)
        names = [item.get("name") if isinstance(item, dict) else None for item in value]
        if any(not _nonempty_str(name) for name in names):
            raise ApplyError("LINT-COMPONENT: every component needs a name", code=2)
        if len(set(names)) != len(names):
            raise ApplyError("LINT-COMPONENT: duplicate component names are not allowed", code=2)
    elif rule == "LINT-PRIORITY":
        if value is None and revert:
            return
        if not isinstance(value, dict) or not _nonempty_str(value.get("name")):
            raise ApplyError("LINT-PRIORITY: priority must be {name: ...}", code=2)
        priority = value["name"]
        if priority in PRIORITIES_DIRECT:
            return
        if priority in PRIORITIES_INHERITED:
            if evidence.get("parent_priority") != priority or not _issue_key(
                evidence.get("parent")
            ):
                raise ApplyError(
                    f"LINT-PRIORITY: {priority} is only allowed when inherited from a parent",
                    code=2,
                )
            return
        raise ApplyError(f"LINT-PRIORITY: unsupported priority {priority!r}", code=2)
    elif rule == "LINT-POINTS":
        if value is None and revert:
            return
        if not isinstance(value, int) or isinstance(value, bool) or value not in POINTS:
            raise ApplyError("LINT-POINTS: story points must be 1, 2, 3, 5, or 8", code=2)
    elif rule == "LINT-SIZE":
        if value is None and revert:
            return
        if not isinstance(value, str) or value not in SIZES:
            raise ApplyError("LINT-SIZE: size must be XS, S, M, L, or XL", code=2)
    elif rule == "LINT-FIXVERSION-MULTI":
        if value == [] and revert:
            return
        if not isinstance(value, list) or len(value) != 1:
            raise ApplyError("LINT-FIXVERSION-MULTI: exactly one fix version is allowed", code=2)
        item = value[0]
        if not isinstance(item, dict) or not _nonempty_str(item.get("name")):
            raise ApplyError("LINT-FIXVERSION-MULTI: fix version needs a name", code=2)
        if item["name"] != evidence.get("chosen_version") or item["name"] not in evidence.get(
            "current_versions", []
        ):
            raise ApplyError(
                "LINT-FIXVERSION-MULTI: value does not match the recorded evidence", code=2
            )
    elif rule == "LINT-RN-TYPE":
        if value is None and revert:
            return
        if not isinstance(value, dict) or not _nonempty_str(value.get("value")):
            raise ApplyError("LINT-RN-TYPE: release note type must be {value: ...}", code=2)
    elif rule == "LINT-RN-TEXT":
        if value is None and revert:
            return
        if not adf_nonempty(value):
            raise ApplyError(
                "LINT-RN-TEXT: release note text must be a non-empty ADF document", code=2
            )
    elif rule == "LINT-RN-STATUS":
        if value is None and revert:
            return
        if not isinstance(value, dict) or value.get("value") != "Proposed":
            raise ApplyError("LINT-RN-STATUS: only Proposed is allowed", code=2)
    else:
        raise ApplyError(f"{rule}: rule does not support writes", code=2)


def validate_plan(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
    if not isinstance(plan, dict):
        raise ApplyError("plan must be an object", code=2)
    _require_keys(plan, PLAN_KEYS, "plan")
    if plan.get("schema") != 2:
        raise ApplyError("plan.schema must be 2", code=2)
    if not _nonempty_str(plan.get("run_id")):
        raise ApplyError("plan.run_id is required", code=2)
    if not isinstance(plan.get("scan_digest"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", plan["scan_digest"]
    ):
        raise ApplyError("plan.scan_digest must be a sha256 hex digest", code=2)
    scope = plan.get("scope")
    if not isinstance(scope, dict):
        raise ApplyError("plan.scope must be an object", code=2)
    if not (_nonempty_str(scope.get("jql")) or isinstance(scope.get("issue_keys"), list)):
        raise ApplyError("plan.scope needs jql or issue_keys", code=2)
    fields = plan.get("fields")
    if not isinstance(fields, dict):
        raise ApplyError("plan.fields must be an object", code=2)
    issues = plan.get("issues")
    if not isinstance(issues, list) or not issues:
        raise ApplyError("plan.issues must be a non-empty list", code=2)
    scope_issue_keys = scope.get("issue_keys")
    if scope_issue_keys is not None and (
        not isinstance(scope_issue_keys, list)
        or any(not _issue_key(key) for key in scope_issue_keys)
    ):
        raise ApplyError("plan.scope.issue_keys must contain valid issue keys", code=2)

    seen_fields: set[tuple[str, str]] = set()
    issue_count = 0
    operation_count = 0
    for issue in issues:
        if not isinstance(issue, dict):
            raise ApplyError("each issue must be an object", code=2)
        _require_keys(issue, ISSUE_KEYS, f"issue {issue.get('key', '?')}")
        key = issue.get("key")
        if not _issue_key(key):
            raise ApplyError(f"invalid issue key {key!r}", code=2)
        if scope_issue_keys is not None and key not in scope_issue_keys:
            raise ApplyError(f"{key}: issue is outside plan.scope.issue_keys", code=2)
        if issue.get("project") not in PROJECTS:
            raise ApplyError(f"{key}: project is outside the allowed set", code=2)
        if issue.get("status") in EXCLUDED_STATUSES:
            raise ApplyError(f"{key}: status {issue['status']!r} is excluded", code=2)
        if issue.get("issuetype") in EXCLUDED_TYPES:
            raise ApplyError(f"{key}: issue type {issue['issuetype']!r} is excluded", code=2)
        if (
            not _nonempty_str(issue.get("summary"))
            or "[test execution]" in issue["summary"].lower()
        ):
            raise ApplyError(f"{key}: summary is missing or excluded", code=2)
        if not isinstance(issue.get("labels"), list):
            raise ApplyError(f"{key}: labels must be a list", code=2)
        if not _nonempty_str(issue.get("expected_updated")):
            raise ApplyError(f"{key}: expected_updated is required", code=2)
        mention = issue.get("mention")
        if mention is not None and not (
            isinstance(mention, dict) and _nonempty_str(mention.get("accountId"))
        ):
            raise ApplyError(f"{key}: mention must carry an accountId", code=2)
        findings = issue.get("findings")
        if not isinstance(findings, list) or not findings:
            raise ApplyError(f"{key}: findings must be a non-empty list", code=2)
        issue_count += 1
        for finding in findings:
            if not isinstance(finding, dict):
                raise ApplyError(f"{key}: each finding must be an object", code=2)
            _require_keys(finding, FINDING_KEYS, f"{key} finding")
            rule = finding.get("rule")
            if rule not in RULES:
                raise ApplyError(f"{key}: unknown rule {rule!r}", code=2)
            if finding.get("action") not in ACTIONS:
                raise ApplyError(f"{key}/{rule}: unknown action", code=2)
            decision = finding.get("decision")
            if decision not in DECISIONS:
                raise ApplyError(f"{key}/{rule}: unknown decision", code=2)
            _validate_evidence(rule, finding.get("evidence"), decision)
            if decision != "supported":
                if finding.get("set") is not None or finding.get("precondition") is not None:
                    raise ApplyError(
                        f"{key}/{rule}: non-supported findings cannot carry writes", code=2
                    )
                continue
            if rule not in WRITE_RULES:
                raise ApplyError(f"{key}/{rule}: rule does not support writes", code=2)
            logical_field = WRITE_RULES[rule]
            field = (
                logical_field
                if logical_field in {"components", "priority", "fixVersions"}
                else fields.get(logical_field)
            )
            if not _nonempty_str(field):
                raise ApplyError(f"{key}/{rule}: field {logical_field!r} is not resolved", code=2)
            if (key, field) in seen_fields:
                raise ApplyError(f"{key}/{rule}: duplicate write for field {field!r}", code=2)
            seen_fields.add((key, field))
            set_payload = finding.get("set")
            if not isinstance(set_payload, dict) or set_payload.keys() != {"fields"}:
                raise ApplyError(f"{key}/{rule}: set must be {{fields: ...}}", code=2)
            payload_fields = set_payload["fields"]
            if not isinstance(payload_fields, dict) or list(payload_fields) != [field]:
                raise ApplyError(f"{key}/{rule}: set.fields must contain exactly {field!r}", code=2)
            precondition = finding.get("precondition")
            if not isinstance(precondition, dict):
                raise ApplyError(f"{key}/{rule}: precondition is required", code=2)
            if precondition.keys() not in ({"field", "state"}, {"field", "state", "value"}):
                raise ApplyError(f"{key}/{rule}: invalid precondition keys", code=2)
            if precondition.get("field") != field:
                raise ApplyError(f"{key}/{rule}: precondition field must match the write", code=2)
            if precondition.get("state") not in {"empty", "equals"}:
                raise ApplyError(
                    f"{key}/{rule}: precondition.state must be empty or equals", code=2
                )
            if precondition.get("state") == "equals" and "value" not in precondition:
                raise ApplyError(f"{key}/{rule}: equals precondition needs a value", code=2)
            _validate_value(
                rule,
                field,
                payload_fields[field],
                finding["evidence"],
                revert=precondition.get("state") == "equals",
            )
            operation_count += 1
    if issue_count > 50:
        raise ApplyError(f"plan has {issue_count} issues; the hard limit is 50", code=2)
    if operation_count > 50:
        raise ApplyError(f"plan has {operation_count} operations; the hard limit is 50", code=2)
    return issues, issue_count, operation_count


def _issue_fields(issue: dict[str, Any], fields: dict[str, str]) -> list[str]:
    result = {
        "summary",
        "status",
        "issuetype",
        "priority",
        "parent",
        "components",
        "fixVersions",
        "project",
        "labels",
        "updated",
    }
    for finding in issue["findings"]:
        if finding.get("decision") != "supported":
            continue
        rule = finding["rule"]
        logical = WRITE_RULES[rule]
        if logical not in result:
            result.add(fields.get(logical, logical))
    return sorted(result)


def read_issue(credential: str, key: str, field_ids: list[str]) -> dict[str, Any]:
    query = urllib.parse.urlencode({"fields": ",".join(dict.fromkeys(field_ids))})
    payload = request_with_retry(f"/rest/api/3/issue/{urllib.parse.quote(key)}?{query}", credential)
    return payload or {}


def write_issue(credential: str, key: str, fields: dict[str, Any]) -> None:
    request_with_retry(
        f"/rest/api/3/issue/{urllib.parse.quote(key)}?notifyUsers=false",
        credential,
        method="PUT",
        body={"fields": fields},
    )


def issue_in_scope(current: dict[str, Any], planned: dict[str, Any]) -> tuple[bool, str]:
    fields = current.get("fields") or {}
    project = (fields.get("project") or {}).get("key") or ""
    status = (fields.get("status") or {}).get("name") or ""
    issue_type = (fields.get("issuetype") or {}).get("name") or ""
    summary = fields.get("summary") or ""
    updated = fields.get("updated") or ""
    if project != planned["project"]:
        return False, f"project changed from {planned['project']} to {project or 'unknown'}"
    if status != planned["status"]:
        return False, f"status changed from {planned['status']} to {status or 'unknown'}"
    if issue_type != planned["issuetype"]:
        return False, f"issue type changed from {planned['issuetype']} to {issue_type or 'unknown'}"
    if "[test execution]" in summary.lower():
        return False, "summary is now excluded as [test execution]"
    if updated != planned["expected_updated"]:
        return False, f"issue changed since scan (updated {updated or 'unknown'})"
    return True, ""


def precondition_holds(precondition: dict[str, Any], current: Any) -> bool:
    state = precondition.get("state")
    if state == "empty":
        return not has_value(current)
    if state == "equals":
        return values_match(precondition.get("value"), current)
    raise ApplyError(f"unknown precondition state {state!r}", code=2)


def batch_id(issue: dict[str, Any], run_id: str) -> str:
    material = {
        "run_id": run_id,
        "key": issue["key"],
        "supported": [
            {
                "rule": finding["rule"],
                "set": finding.get("set"),
                "evidence": finding.get("evidence"),
            }
            for finding in issue["findings"]
            if finding.get("decision") == "supported"
        ],
        "not_changed": [
            {"rule": finding["rule"], "decision": finding.get("decision")}
            for finding in issue["findings"]
            if finding.get("decision") != "supported"
        ],
    }
    return digest(material)[:12]


def _paragraph(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "paragraph", "content": nodes}


def _text_node(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _bullet(text: str) -> dict[str, Any]:
    return {
        "type": "paragraph",
        "content": [{"type": "text", "text": text}],
    }


def build_comment_adf(issue: dict[str, Any], run_id: str) -> dict[str, Any]:
    changed = []
    not_changed = []
    for finding in issue["findings"]:
        label = f"{finding['rule']}: {finding.get('reason') or finding['evidence'].get('basis')}"
        if finding.get("decision") == "supported":
            changed.append(label)
        else:
            reason = finding.get("reason") or finding["evidence"].get("basis")
            not_changed.append(f"{label} — {reason}")
    content = [
        _paragraph(
            [_text_node(f"{COMMENT_MARKER} Automated hygiene update ({batch_id(issue, run_id)}).")]
        )
    ]
    if changed:
        content.append(_paragraph([_text_node("What changed")]))
        content.extend(_bullet(f"- {item}") for item in changed)
    if not_changed:
        content.append(_paragraph([_text_node("What wasn’t changed")]))
        content.extend(_bullet(f"- {item}") for item in not_changed)
    content.append(_paragraph([_text_node("No existing values were overwritten.")]))
    mention = issue.get("mention")
    if mention and mention.get("accountId"):
        name = str(mention.get("displayName") or "there")
        content.append(
            _paragraph(
                [
                    {
                        "type": "mention",
                        "attrs": {"id": str(mention["accountId"]), "text": f"@{name}"},
                    },
                    _text_node(" — review the reasoning above; reply if it is wrong."),
                ]
            )
        )
    return {"type": "doc", "version": 1, "content": content}


def comment_text(body: Any) -> str:
    return " ".join(_text(body).split())


def all_comments(credential: str, key: str) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    start = 0
    while True:
        query = urllib.parse.urlencode({"startAt": start, "maxResults": 100})
        payload = (
            request_with_retry(
                f"/rest/api/3/issue/{urllib.parse.quote(key)}/comment?{query}", credential
            )
            or {}
        )
        batch = payload.get("comments") or []
        comments.extend(batch)
        total = int(payload.get("total") or len(comments))
        start += len(batch)
        if not batch or start >= total:
            return comments


def visibility_matches(comment: dict[str, Any]) -> bool:
    visibility = comment.get("visibility") or {}
    return (
        visibility.get("type") == COMMENT_VISIBILITY["type"]
        and visibility.get("value") == COMMENT_VISIBILITY["value"]
    )


def upsert_comment(
    credential: str,
    issue: dict[str, Any],
    run_id: str,
    adf: dict[str, Any],
) -> dict[str, Any]:
    key = issue["key"]
    expected_batch = batch_id(issue, run_id)
    existing = [
        comment
        for comment in all_comments(credential, key)
        if COMMENT_MARKER in comment_text(comment.get("body"))
        and expected_batch in comment_text(comment.get("body"))
    ]
    if existing:
        comment = existing[0]
        if not visibility_matches(comment):
            return {
                "key": key,
                "batch": expected_batch,
                "status": "failed",
                "error": "existing comment does not have Red Hat Employee visibility",
            }
        return {
            "key": key,
            "batch": expected_batch,
            "status": "unchanged",
            "comment_id": comment.get("id"),
        }
    created = (
        request_with_retry(
            f"/rest/api/3/issue/{urllib.parse.quote(key)}/comment?notifyUsers=false",
            credential,
            method="POST",
            body={"body": adf, "visibility": COMMENT_VISIBILITY},
        )
        or {}
    )
    verified = [
        comment
        for comment in all_comments(credential, key)
        if COMMENT_MARKER in comment_text(comment.get("body"))
        and expected_batch in comment_text(comment.get("body"))
    ]
    if not verified:
        return {
            "key": key,
            "batch": expected_batch,
            "status": "failed",
            "error": "comment read-back did not match",
        }
    comment = verified[0]
    if not visibility_matches(comment):
        return {
            "key": key,
            "batch": expected_batch,
            "status": "failed",
            "error": "comment read-back does not have Red Hat Employee visibility",
        }
    if comment_text(comment.get("body")) != comment_text(adf):
        return {
            "key": key,
            "batch": expected_batch,
            "status": "failed",
            "error": "comment read-back body did not match",
        }
    return {
        "key": key,
        "batch": expected_batch,
        "status": "created",
        "comment_id": created.get("id") or comment.get("id"),
    }


def _finding_outcome(
    finding: dict[str, Any],
    status: str,
    *,
    before: Any = None,
    after: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    outcome = {
        "rule": finding["rule"],
        "action": finding["action"],
        "decision": finding["decision"],
        "status": status,
    }
    outcome["before"] = before
    outcome["after"] = after
    outcome["before_display"] = normalize(before)
    outcome["after_display"] = normalize(after)
    if error:
        outcome["error"] = error
    return outcome


def run_issue(
    credential: str,
    issue: dict[str, Any],
    fields: dict[str, str],
    run_id: str,
    stopped_rules: set[str],
    dry_run: bool,
) -> dict[str, Any]:
    key = issue["key"]
    result: dict[str, Any] = {
        "key": key,
        "status": "pending",
        "findings": [],
        "comment": None,
    }
    field_ids = _issue_fields(issue, fields)
    try:
        current = read_issue(credential, key, field_ids)
    except ApplyError as exc:
        if exc.status in {401, 403}:
            raise FatalRunError(str(exc)) from exc
        result.update(status="failed", error=str(exc))
        return result
    in_scope, scope_error = issue_in_scope(current, issue)
    if not in_scope:
        result.update(status="skipped", error=scope_error)
        return result

    decision_status = {
        "insufficient": "blocked",
        "human_required": "escalated",
        "waived": "waived",
    }
    for finding in issue["findings"]:
        if finding.get("decision") != "supported":
            result["findings"].append(
                _finding_outcome(finding, decision_status[finding["decision"]])
            )
    supported = [finding for finding in issue["findings"] if finding.get("decision") == "supported"]
    if not supported:
        decisions = {finding["decision"] for finding in issue["findings"]}
        if "insufficient" in decisions:
            result["status"] = "blocked"
        elif "human_required" in decisions:
            result["status"] = "escalated"
        else:
            result["status"] = "waived"
        return result

    for finding in supported:
        if finding["rule"] != "LINT-PRIORITY":
            continue
        priority = finding["set"]["fields"]["priority"].get("name")
        if priority not in PRIORITIES_INHERITED:
            continue
        parent_key = finding["evidence"].get("parent")
        current_parent = (current.get("fields") or {}).get("parent") or {}
        if current_parent.get("key") != parent_key:
            result.update(
                status="skipped",
                error=f"parent changed from {parent_key} to {current_parent.get('key') or 'unknown'}",
            )
            return result
        try:
            parent_issue = read_issue(credential, str(parent_key), ["priority"])
        except ApplyError as exc:
            if exc.status in {401, 403}:
                raise FatalRunError(str(exc)) from exc
            result.update(status="failed", error=str(exc))
            return result
        parent_priority = ((parent_issue.get("fields") or {}).get("priority") or {}).get("name")
        if parent_priority != priority:
            result.update(
                status="skipped",
                error=f"parent priority changed from {priority} to {parent_priority or 'unknown'}",
            )
            return result

    payload: dict[str, Any] = {}
    before_values: dict[str, Any] = {}
    for finding in supported:
        rule = finding["rule"]
        if rule in stopped_rules:
            result["findings"].append(
                _finding_outcome(finding, "skipped", error="rule stopped earlier in run")
            )
            result["status"] = "failed"
            return result
        field = list(finding["set"]["fields"])[0]
        current_value = (current.get("fields") or {}).get(field)
        before_values[field] = current_value
        if not precondition_holds(finding["precondition"], current_value):
            result["findings"].append(
                _finding_outcome(
                    finding,
                    "skipped",
                    before=current_value,
                    error="precondition failed",
                )
            )
            result["status"] = "skipped"
            return result
        payload[field] = finding["set"]["fields"][field]

    if dry_run:
        result["status"] = "planned"
        result["payload"] = {"fields": payload}
        return result

    try:
        write_issue(credential, key, payload)
    except ApplyError as exc:
        if exc.status == 401:
            raise FatalRunError(str(exc)) from exc
        if exc.status in {400, 403, 429}:
            stopped_rules.update(finding["rule"] for finding in supported)
        result.update(status="failed", error=str(exc))
        return result

    try:
        after = read_issue(credential, key, field_ids)
    except ApplyError as exc:
        if exc.status in {401, 403}:
            raise FatalRunError(str(exc)) from exc
        result.update(status="failed", error=f"write accepted but read-back failed: {exc}")
        return result

    result["updated_after"] = (after.get("fields") or {}).get("updated")
    mismatches = []
    for finding in supported:
        field = list(finding["set"]["fields"])[0]
        expected = finding["set"]["fields"][field]
        actual = (after.get("fields") or {}).get(field)
        if values_match(expected, actual):
            result["findings"].append(
                _finding_outcome(finding, "completed", before=before_values[field], after=actual)
            )
        else:
            mismatches.append(
                {
                    "rule": finding["rule"],
                    "field": field,
                    "expected": normalize(expected),
                    "actual": normalize(actual),
                }
            )
    if mismatches:
        stopped_rules.update(finding["rule"] for finding in supported)
        result.update(status="failed", error="read-back did not match", mismatches=mismatches)
        return result

    adf = build_comment_adf(issue, run_id)
    try:
        comment_outcome = upsert_comment(credential, issue, run_id, adf)
    except ApplyError as exc:
        if exc.status == 401:
            raise FatalRunError(str(exc)) from exc
        result.update(status="failed", error=f"comment failed: {exc}")
        return result
    result["comment"] = comment_outcome
    try:
        post_comment = read_issue(credential, key, field_ids)
        result["updated_after"] = (post_comment.get("fields") or {}).get("updated")
    except ApplyError as exc:
        if exc.status in {401, 403}:
            raise FatalRunError(str(exc)) from exc
        result.update(status="failed", error=f"post-comment read failed: {exc}")
        return result
    result["status"] = "failed" if comment_outcome.get("status") == "failed" else "completed"
    return result


def build_revert_plan(plan: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    issues = []
    for issue_result in receipt.get("issues", []):
        key = issue_result.get("key")
        planned_issue = next((item for item in plan["issues"] if item["key"] == key), None)
        if not planned_issue:
            continue
        findings = []
        for outcome in issue_result.get("findings", []):
            rule = outcome.get("rule")
            planned_finding = next(
                (item for item in planned_issue["findings"] if item["rule"] == rule), None
            )
            if not planned_finding or outcome.get("status") != "completed":
                continue
            field = list(planned_finding["set"]["fields"])[0]
            before = outcome.get("before")
            after = planned_finding["set"]["fields"][field]
            findings.append(
                {
                    "rule": rule,
                    "action": planned_finding["action"],
                    "decision": "supported",
                    "evidence": planned_finding["evidence"],
                    "reason": f"revert {rule} on {key}",
                    "set": {"fields": {field: before}},
                    "precondition": {"field": field, "state": "equals", "value": after},
                }
            )
        if findings:
            updated_after = issue_result.get("updated_after") or planned_issue["expected_updated"]
            issues.append(
                {**planned_issue, "findings": findings, "expected_updated": updated_after}
            )
    return {
        "schema": 2,
        "run_id": f"revert-{plan['run_id']}",
        "scan_digest": plan["scan_digest"],
        "scope": plan["scope"],
        "fields": plan["fields"],
        "issues": issues,
    }


def write_json_atomic(path: str, value: Any) -> None:
    target = Path(path)
    temporary = Path(f"{target}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a hardened Jira lint remediation plan.")
    parser.add_argument("--plan", required=True, help="Path to the schema 2 plan JSON.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Check preconditions, write nothing."
    )
    parser.add_argument("--confirm", action="store_true", help="Required to write.")
    parser.add_argument("--receipt", help="Required with --confirm.")
    parser.add_argument("--revert-plan", help="Optional path for the guarded revert plan.")
    args = parser.parse_args(argv)

    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        issues, issue_count, operation_count = validate_plan(plan)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read plan: {exc}", file=sys.stderr)
        return 2
    except ApplyError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code

    if args.dry_run and args.confirm:
        print("choose either --dry-run or --confirm, not both", file=sys.stderr)
        return 2
    if not args.dry_run and not args.confirm:
        print("refusing to write without --confirm (or use --dry-run)", file=sys.stderr)
        return 2
    if args.confirm and not args.receipt:
        print("--receipt is required with --confirm", file=sys.stderr)
        return 2
    if args.confirm and not args.revert_plan:
        print("--revert-plan is required with --confirm", file=sys.stderr)
        return 2

    try:
        credential = load_email_token()
    except ApplyError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code

    stopped_rules: set[str] = set()
    results: list[dict[str, Any]] = []
    fatal_error: str | None = None
    counts = {
        "completed": 0,
        "planned": 0,
        "skipped": 0,
        "failed": 0,
        "blocked": 0,
        "escalated": 0,
        "waived": 0,
    }

    def render_receipt() -> dict[str, Any]:
        receipt = {
            "schema": 2,
            "run_id": plan["run_id"],
            "plan_hash": plan_hash(plan),
            "scan_digest": plan["scan_digest"],
            "jira_host": JIRA_HOST,
            "generated": datetime.now().isoformat(timespec="seconds"),
            "mode": "dry-run" if args.dry_run else "apply",
            "scope": plan["scope"],
            "fields": plan["fields"],
            "counts": counts,
            "issue_count": issue_count,
            "operation_count": operation_count,
            "stopped_rules": sorted(stopped_rules),
            "issues": results,
        }
        if fatal_error:
            receipt["fatal_error"] = fatal_error
        return receipt

    for issue in issues:
        try:
            result = run_issue(
                credential,
                issue,
                plan["fields"],
                plan["run_id"],
                stopped_rules,
                args.dry_run,
            )
            results.append(result)
            counts[result["status"]] = counts.get(result["status"], 0) + 1
        except FatalRunError as exc:
            fatal_error = str(exc)
            break

        if args.receipt:
            write_json_atomic(args.receipt, render_receipt())
        if args.confirm and args.revert_plan:
            revert = build_revert_plan(plan, render_receipt())
            if revert["issues"]:
                write_json_atomic(args.revert_plan, revert)

    if args.receipt:
        write_json_atomic(args.receipt, render_receipt())
        print(f"receipt written to {args.receipt}")
    else:
        print(json.dumps(render_receipt(), indent=2))

    if args.confirm and args.revert_plan:
        revert = build_revert_plan(plan, render_receipt())
        if revert["issues"]:
            write_json_atomic(args.revert_plan, revert)
            print(f"revert plan written to {args.revert_plan}")

    return 1 if fatal_error or counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
