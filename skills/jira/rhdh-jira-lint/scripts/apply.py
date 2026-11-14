#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Apply a Jira lint remediation plan, then verify every change by read-back.

The plan is produced by the lint sweep after its standard-procedure pass and is
approved through the write gate. This script is the batch executor: it checks
each operation's precondition, writes the field payload, reads the issue back,
records one outcome per operation, and posts one receipt comment per issue.

Comments are identified by a marker plus a batch hash, so a retry of the same
change is a no-op while a genuinely new batch of changes gets its own comment.
Nothing is ever stacked twice.

Plan shape:

  {
    "schema": 1,
    "operations": [
      {
        "key": "RHIDP-1234",
        "rule": "LINT-COMPONENT",
        "set": {"fields": {"components": [{"name": "Catalog"}]}},
        "precondition": {"field": "components", "state": "empty"}
      }
    ],
    "comments": [
      {
        "key": "RHIDP-1234",
        "lines": ["Component -> Catalog (inherited from RHIDP-1100)."],
        "mention": {"accountId": "...", "displayName": "Jane Doe", "role": "assignee"}
      }
    ]
  }

Usage:
  uv run scripts/apply.py --plan /tmp/lint-plan.json --dry-run
  uv run scripts/apply.py --plan /tmp/lint-plan.json --confirm --receipt /tmp/lint-receipt.json

Token discovery matches scan.py: JIRA_TOKEN_FILE, else `.jira-token` next to
acli. Never printed. Optional JIRA_BASE_URL.

Exit codes: 0 every operation completed or unchanged; 1 one or more failed or
skipped; 2 bad plan; 3 no credentials; 4 Jira request failed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_BASE = "https://redhat.atlassian.net"
COMMENT_MARKER = "[rhdh-jira-lint]"


class ApplyError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: int = 4):
        super().__init__(message)
        self.status = status
        self.code = code


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
        raise ApplyError(
            "Jira token file not found next to acli (or JIRA_TOKEN_FILE); "
            "run /setup-rhdh-skills atlassian-mcp or authenticate acli.",
            code=3,
        )
    line = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    if ":" not in line:
        raise ApplyError("the Jira token file is not in `email:token` form", code=3)
    return line


def request(
    base: str,
    path: str,
    credential: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    encoded = base64.b64encode(credential.encode("utf-8")).decode("ascii")
    req = urllib.request.Request(f"{base.rstrip('/')}{path}", data=data, method=method)
    req.add_header("Authorization", f"Basic {encoded}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise ApplyError(
            f"{method} {path} failed with HTTP {exc.code}: {detail}", status=exc.code
        ) from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"{method} {path} could not reach Jira: {exc.reason}") from exc
    return json.loads(payload) if payload.strip() else None


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
    if isinstance(raw, (list, tuple)):
        return any(has_value(item) for item in raw)
    return bool(str(raw).strip())


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


def precondition_holds(state: str, current: Any) -> bool:
    if state == "empty":
        return not has_value(current)
    if state == "any":
        return True
    raise ApplyError(f"unknown precondition state {state!r}", code=2)


# --------------------------------------------------------------------------- #
# Comments
# --------------------------------------------------------------------------- #


def _paragraph(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "paragraph", "content": nodes}


def _text_node(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def batch_id(lines: list[str], mention: dict[str, Any] | None = None) -> str:
    """A stable id for one batch of changes, so a retry is recognisable."""
    account = str((mention or {}).get("accountId") or "")
    material = "\n".join(line.strip() for line in lines) + "\x00" + account
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:8]


def build_comment_adf(lines: list[str], mention: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the receipt comment. The marker plus batch id makes a retry find it."""
    marker_line = f"{COMMENT_MARKER} Automated hygiene update ({batch_id(lines, mention)})."
    content = [_paragraph([_text_node(marker_line)])]
    for line in lines:
        content.append(_paragraph([_text_node(line)]))
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


def _marker_comments(base: str, credential: str, key: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"maxResults": 100, "expand": "body"})
    payload = (
        request(base, f"/rest/api/3/issue/{urllib.parse.quote(key)}/comment?{query}", credential)
        or {}
    )
    return [
        comment
        for comment in payload.get("comments") or []
        if COMMENT_MARKER in comment_text(comment.get("body"))
    ]


def upsert_comment(
    base: str,
    credential: str,
    key: str,
    adf: dict[str, Any],
    *,
    lines: list[str],
    mention: dict[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any]:
    """Post one comment per distinct batch; a retry of the same batch is a no-op."""
    outcome: dict[str, Any] = {
        "key": key,
        "batch": batch_id(lines, mention),
        "status": "pending",
    }
    existing = _marker_comments(base, credential, key)
    same_batch = [
        comment
        for comment in existing
        if f"({outcome['batch']})" in comment_text(comment.get("body"))
    ]
    if same_batch:
        outcome["status"] = "unchanged"
        outcome["comment_id"] = same_batch[0].get("id")
        return outcome

    if dry_run:
        outcome["status"] = "planned"
        outcome["mode"] = "create"
        return outcome

    created = (
        request(
            base,
            f"/rest/api/3/issue/{urllib.parse.quote(key)}/comment",
            credential,
            method="POST",
            body={"body": adf},
        )
        or {}
    )
    outcome["status"] = "created"
    outcome["comment_id"] = created.get("id")

    verified = _marker_comments(base, credential, key)
    if not any(
        f"({outcome['batch']})" in comment_text(comment.get("body")) for comment in verified
    ):
        outcome["status"] = "failed"
        outcome["error"] = "comment read-back did not match"
    return outcome


# --------------------------------------------------------------------------- #
# Field operations
# --------------------------------------------------------------------------- #


def read_issue(base: str, credential: str, key: str, field_ids: list[str]) -> dict[str, Any]:
    fields = list(dict.fromkeys([*field_ids, "status", "labels"]))
    query = urllib.parse.urlencode({"fields": ",".join(fields)})
    payload = request(base, f"/rest/api/3/issue/{urllib.parse.quote(key)}?{query}", credential)
    return payload or {}


def run_operation(
    base: str, credential: str, operation: dict[str, Any], *, dry_run: bool
) -> dict[str, Any]:
    key = operation["key"]
    payload_fields = operation["set"]["fields"]
    precondition = operation.get("precondition") or {"field": None, "state": "any"}
    field_ids = list(payload_fields)
    if precondition.get("field"):
        field_ids.append(precondition["field"])

    outcome: dict[str, Any] = {
        "key": key,
        "rule": operation.get("rule"),
        "reason": operation.get("reason"),
        "fields": field_ids,
        "status": "pending",
    }
    try:
        before = read_issue(base, credential, key, field_ids)
    except ApplyError as exc:
        outcome.update(status="failed", error=str(exc), http_status=exc.status)
        return outcome

    current = (before.get("fields") or {}).get(precondition.get("field"))
    if not precondition_holds(precondition.get("state", "any"), current):
        outcome.update(
            status="skipped",
            reason=(
                f"precondition failed: {precondition.get('field')} is not "
                f"{precondition.get('state')}"
            ),
            before=normalize(current),
        )
        return outcome

    outcome["before"] = {
        field_id: normalize((before.get("fields") or {}).get(field_id)) for field_id in field_ids
    }

    if dry_run:
        outcome.update(status="planned", payload={"fields": payload_fields})
        return outcome

    try:
        request(
            base,
            f"/rest/api/3/issue/{urllib.parse.quote(key)}",
            credential,
            method="PUT",
            body={"fields": payload_fields},
        )
    except ApplyError as exc:
        outcome.update(status="failed", error=str(exc), http_status=exc.status)
        return outcome

    try:
        after = read_issue(base, credential, key, field_ids)
    except ApplyError as exc:
        outcome.update(status="failed", error=f"write accepted but read-back failed: {exc}")
        return outcome

    mismatches = []
    for field_id, expected in payload_fields.items():
        actual = (after.get("fields") or {}).get(field_id)
        if not values_match(expected, actual):
            mismatches.append(
                {"field": field_id, "expected": normalize(expected), "actual": normalize(actual)}
            )
    outcome["after"] = {
        field_id: normalize((after.get("fields") or {}).get(field_id)) for field_id in field_ids
    }
    if mismatches:
        outcome.update(status="failed", error="read-back did not match", mismatches=mismatches)
    else:
        outcome["status"] = "completed"
    return outcome


def validate_plan(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    operations = plan.get("operations") or []
    comments = plan.get("comments") or []
    if not isinstance(operations, list) or not isinstance(comments, list):
        raise ApplyError("operations and comments must be lists", code=2)
    if not operations and not comments:
        raise ApplyError("plan has no operations and no comments", code=2)

    for operation in operations:
        if not isinstance(operation, dict):
            raise ApplyError("each operation must be an object", code=2)
        key = operation.get("key")
        if not isinstance(key, str) or not key:
            raise ApplyError("an operation is missing its issue key", code=2)
        fields = (operation.get("set") or {}).get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ApplyError(f"{key}: set.fields is empty", code=2)
        precondition = operation.get("precondition") or {"field": None, "state": "any"}
        if precondition.get("state", "any") not in ("empty", "any"):
            raise ApplyError(f"{key}: unknown precondition state", code=2)

    for comment in comments:
        if not isinstance(comment, dict):
            raise ApplyError("each comment must be an object", code=2)
        key = comment.get("key")
        if not isinstance(key, str) or not key:
            raise ApplyError("a comment is missing its issue key", code=2)
        lines = comment.get("lines")
        if (
            not isinstance(lines, list)
            or not lines
            or any(not isinstance(line, str) or not line.strip() for line in lines)
        ):
            raise ApplyError(f"{key}: comment lines must be non-empty strings", code=2)
        mention = comment.get("mention")
        if mention is not None and not (
            isinstance(mention, dict) and isinstance(mention.get("accountId"), str)
        ):
            raise ApplyError(f"{key}: mention must carry an accountId", code=2)

    return operations, comments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a Jira lint remediation plan.")
    parser.add_argument("--plan", required=True, help="Path to the plan JSON.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Check preconditions, write nothing."
    )
    parser.add_argument("--confirm", action="store_true", help="Required to write.")
    parser.add_argument(
        "--max-operations",
        type=int,
        default=50,
        help="Refuse a plan larger than this; a huge plan is a rule or scope error.",
    )
    parser.add_argument("--receipt", help="Write the receipt here instead of stdout.")
    args = parser.parse_args(argv)

    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        operations, comments = validate_plan(plan)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read plan: {exc}", file=sys.stderr)
        return 2
    except ApplyError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code

    if not args.dry_run and not args.confirm:
        print("refusing to write without --confirm (or use --dry-run)", file=sys.stderr)
        return 2

    if len(operations) > args.max_operations:
        print(
            f"refusing a plan with {len(operations)} operations; the limit is "
            f"{args.max_operations}. Narrow the scope or split the sweep.",
            file=sys.stderr,
        )
        return 2

    base = os.environ.get("JIRA_BASE_URL", DEFAULT_BASE).rstrip("/")
    try:
        credential = load_email_token()
    except ApplyError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code

    outcomes = []
    for operation in operations:
        try:
            outcomes.append(run_operation(base, credential, operation, dry_run=args.dry_run))
        except ApplyError as exc:
            outcomes.append(
                {
                    "key": operation.get("key"),
                    "rule": operation.get("rule"),
                    "status": "failed",
                    "error": str(exc),
                }
            )

    comment_outcomes = []
    for comment in comments:
        adf = build_comment_adf(comment["lines"], comment.get("mention"))
        try:
            comment_outcomes.append(
                upsert_comment(
                    base,
                    credential,
                    comment["key"],
                    adf,
                    lines=comment["lines"],
                    mention=comment.get("mention"),
                    dry_run=args.dry_run,
                )
            )
        except ApplyError as exc:
            comment_outcomes.append(
                {"key": comment.get("key"), "status": "failed", "error": str(exc)}
            )

    counts = {"completed": 0, "planned": 0, "skipped": 0, "failed": 0}
    for outcome in outcomes:
        counts[outcome["status"]] = counts.get(outcome["status"], 0) + 1
    comment_counts = {"created": 0, "unchanged": 0, "planned": 0, "failed": 0}
    for outcome in comment_outcomes:
        comment_counts[outcome["status"]] = comment_counts.get(outcome["status"], 0) + 1

    receipt = {
        "schema": 1,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "mode": "dry-run" if args.dry_run else "apply",
        "counts": counts,
        "comment_counts": comment_counts,
        "operations": outcomes,
        "comments": comment_outcomes,
    }
    rendered = json.dumps(receipt, indent=2)
    if args.receipt:
        Path(args.receipt).write_text(rendered + "\n", encoding="utf-8")
        print(f"receipt written to {args.receipt}")
    else:
        print(rendered)
    failed = counts["failed"] or comment_counts["failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
