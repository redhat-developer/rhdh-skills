"""Plan comments without posting them. Jira comments, not dry runs, are history."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta

from .model import Ticket, parse_datetime
from .policy import CLOSE_ACTIONS, EVIDENCE_TYPES, Assessment, Packet

DEFAULT_COOLDOWN_DAYS = 14
MARKER_PREFIX = "rhdh-bug-triage:v1:"
MARKER_RE = re.compile(re.escape(MARKER_PREFIX) + r"([a-f0-9]{64})\b")


def plan_comment(
    ticket: Ticket,
    packet: Packet,
    assessment: Assessment | None,
    as_of: datetime,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
) -> dict:
    """Fail closed on incomplete history, pending work and uncertain delivery.

    The fingerprint ignores prose/ordering changes. Different evidence is not
    permission to repeat a pending request: a cited follow-up is also required.
    This is a dry-run plan, never authorization or an atomic posting lock.
    """
    if cooldown_days < 0:
        raise ValueError("comment cooldown must be nonnegative")
    identity = {
        "key": packet.key,
        "release": packet.current_release,
        "disposition": packet.disposition,
        "action": packet.action,
        "target": packet.target,
        "evidence": sorted({item.ref for item in packet.evidence}),
    }
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    marker = MARKER_PREFIX + fingerprint

    def decision(status: str, reason: str, **details) -> dict:
        return {
            "status": status,
            "reason": reason,
            "reference": marker,
            "cooldownDays": cooldown_days,
            **details,
        }

    if ticket.customer_signals or ticket.is_done:
        return decision("suppress", "Customer-linked or completed issue; no comment proposed.")
    if not ticket.comments_complete:
        return decision(
            "review_required", "Comment history is missing or truncated; fetch it in full."
        )
    body = packet.proposed_comment
    if re.search(r"\bclosing as\b", body, re.I):
        return decision("review_required", "Comment claims a closure instead of recommending one.")
    if packet.action not in CLOSE_ACTIONS and re.search(
        r"\b(?:recommend(?:ation:|ed)?\s+(?:to\s+)?)close\b", body, re.I
    ):
        return decision("review_required", "Comment recommends a close that policy did not permit.")
    citations = re.findall(r"\[[^\]]+\]\((https?://[^\s)]+)\)", body)
    allowed = {item.ref for item in packet.evidence if item.ref.startswith(("http://", "https://"))}
    allowed.update(
        f"https://redhat.atlassian.net/browse/{ref}"
        for ref in [ticket.key, packet.target, *[item.ref for item in packet.evidence]]
        if re.fullmatch(r"[A-Z][A-Z0-9_]+-\d+", ref)
    )
    # A target citation is useful only after the disposition policy selected it.
    if not citations or any(
        url.split("#", 1)[0] not in {ref.split("#", 1)[0] for ref in allowed} for url in citations
    ):
        return decision(
            "review_required", "Comment needs linked evidence from the packet; check its citations."
        )
    unlinked = re.sub(r"\[[^\]]+\]\([^\s)]+\)", "", body)
    if re.search(r"https?://", unlinked):
        return decision("review_required", "Format the evidence URLs as Markdown links.")
    if re.search(r"\b(?:RHDHBUGS|RHIDP|RHDHPLAN|RHDHSUPP|ACCOUNT)-\d+\b", unlinked):
        return decision("review_required", "Link the Jira keys in the proposed comment.")
    prior = []
    for comment in ticket.comments:
        if "rhdh-bug-triage:" not in comment.body:
            continue
        matches = MARKER_RE.findall(comment.body)
        if len(matches) != 1:
            return decision(
                "review_required", "Unrecognized triage reference; reconcile history first."
            )
        if matches[0] == fingerprint:
            return decision(
                "suppress", "The same recommendation is already on Jira.", priorCommentId=comment.id
            )
        created = parse_datetime(comment.created)
        if not created or not comment.id or created > as_of:
            return decision(
                "review_required", "Prior triage comment has no reliable ID or posting time."
            )
        prior.append((created, comment))
    if not prior:
        return decision(
            "propose",
            "No previous marked triage comment; review existing discussion before approval.",
        )
    created, latest = max(prior, key=lambda item: item[0])
    details = {"priorCommentId": latest.id, "lastPostedAt": created.isoformat()}
    earliest = created + timedelta(days=cooldown_days)
    if as_of < earliest:
        return decision(
            "suppress",
            "The comment cooldown has not elapsed.",
            earliestReconsiderAt=earliest.isoformat(),
            **details,
        )
    follow_up = assessment.follow_up if assessment else {}
    evidence = follow_up.get("evidence") or []
    verified_event = (
        follow_up.get("priorCommentId") == latest.id
        and follow_up.get("state") in ("completed", "superseded")
        and isinstance(evidence, list)
        and bool(evidence)
        and all(
            isinstance(item, dict)
            and str(item.get("type")) in EVIDENCE_TYPES
            and isinstance(item.get("ref"), str)
            and item["ref"].strip()
            and isinstance(item.get("why"), str)
            and item["why"].strip()
            and item.get("strength") == "direct"
            for item in evidence
        )
    )
    if not verified_event:
        return decision(
            "suppress",
            "Previous requested action is pending or unverified; time alone is not a reason to comment again.",
            **details,
        )
    return decision(
        "propose",
        "Cooldown elapsed and cited follow-up supports a changed recommendation.",
        followUp=follow_up,
        **details,
    )


def attach_comment_plan(
    ticket: Ticket,
    packet: Packet,
    assessment: Assessment | None,
    as_of: datetime,
    cooldown_days: int,
) -> None:
    packet.comment_plan = plan_comment(ticket, packet, assessment, as_of, cooldown_days)
    # The reference travels in the exact body a human may approve. A future
    # writer must preserve it through Markdown-to-ADF conversion and readback.
    packet.proposed_comment += f"\n\nTriage reference: `{packet.comment_plan['reference']}`."
