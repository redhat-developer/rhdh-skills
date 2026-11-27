"""Plan comments without posting them. Jira comments, not dry runs, are history."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from .model import Ticket, parse_datetime
from .policy import (
    CLOSE_ACTIONS,
    EVIDENCE_TYPES,
    PROOF_FIELDS,
    Assessment,
    Packet,
    _linked_text,
    input_errors,
    next_step_kind,
    recommendation_comment,
    ref_link,
    valid_ref,
    verify_packet,
)

DEFAULT_COOLDOWN_DAYS = 14
MARKER_PREFIX = "rhdh-bug-triage:v1:"
ATTRIBUTION = "rhdh-agentic-bug-triager · AI-generated. Check for accuracy."
MARKER_RE = re.compile(
    rf"(?:{re.escape(MARKER_PREFIX)}|{re.escape(ATTRIBUTION)}\s+`?v1:)([a-f0-9]{{64}})\b"
)


def comment_footer(reference: str) -> str:
    return f"{ATTRIBUTION}  \n`{reference.removeprefix('rhdh-bug-triage:')}`"


def _history_review(ticket: Ticket, assessment: Assessment | None) -> dict | None:
    """Accept an explicit source-linked review of exactly the fetched comments."""
    review = assessment.history_review if assessment and assessment.key == ticket.key else {}
    ids = [comment.id for comment in ticket.comments]
    checked = review.get("checkedCommentIds")
    refs = review.get("refs")
    if (
        review.get("complete") is not True
        or not ids
        or any(not comment_id for comment_id in ids)
        or len(set(ids)) != len(ids)
        or not isinstance(checked, list)
        or any(not isinstance(comment_id, str) for comment_id in checked)
        or len(checked) != len(ids)
        or set(checked) != set(ids)
        or type(review.get("equivalentAdvice")) is not bool
        or type(review.get("pendingAction")) is not bool
        or not isinstance(review.get("summary"), str)
        or not review["summary"].strip()
        or not isinstance(refs, list)
        or not refs
    ):
        return None
    cited_ids = set()
    for ref in refs:
        if not isinstance(ref, str) or not valid_ref(ref) or not ref.startswith("https://"):
            return None
        url = urlsplit(ref)
        if url.netloc != "redhat.atlassian.net":
            return None
        if url.path == "/browse/" + ticket.key:
            focused = parse_qs(url.query).get("focusedCommentId", [])
            comment_id = (
                focused[0]
                if len(focused) == 1
                else url.fragment.removeprefix("comment-")
                if not focused and url.fragment.startswith("comment-")
                else ""
            )
        else:
            match = re.fullmatch(
                r"/rest/api/[23]/issue/" + re.escape(ticket.key) + r"/comment/([^/]+)", url.path
            )
            comment_id = match[1] if match else ""
        if comment_id not in ids:
            return None
        cited_ids.add(comment_id)
    return review if cited_ids == set(ids) else None


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
    # Identity is the advice, not its wording or a growing bibliography. Claim
    # roles are structural semantics; target, fix and validation carry the
    # concrete outcome. Rephrasing a summary cannot clear pending work.
    identity = {
        "key": packet.key,
        "release": packet.current_release,
        "verdict": packet.verdict,
        "target": packet.target,
        "fix": {
            name: packet.fix.get(name, "") for name in ("pr", "commit", "release", "reviewRelease")
        },
        "validation": {
            name: packet.validation.get(name, "") for name in ("release", "method", "result")
        },
        "proof": sorted(
            name
            for name in PROOF_FIELDS.get(packet.verdict, ())
            if isinstance(packet.proof.get(name), dict)
            and isinstance(packet.proof[name].get("summary"), str)
            and packet.proof[name]["summary"].strip()
            and packet.proof[name].get("refs")
        ),
        "nextStep": next_step_kind(packet),
    }
    classification = packet.investigation.get("classification", {})
    if classification.get("kind") in {"feature", "task", "uncertain"}:
        identity["classification"] = [classification["kind"], classification["ref"]]
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

    # Exact repeat suppression does not require a trustworthy timestamp, an ID,
    # or complete history: seeing the marker is enough to avoid another post.
    for comment in ticket.comments:
        if fingerprint in MARKER_RE.findall(comment.body):
            return decision(
                "suppress", "The same recommendation is already on Jira.", priorCommentId=comment.id
            )
    if packet.action not in CLOSE_ACTIONS | {"comment_only"}:
        return decision("suppress", "No triage comment was drafted.")
    if verify_packet(packet, ticket):
        return decision("suppress", "Finding failed re-verification; the draft is not eligible.")
    if ticket.is_done:
        return decision("suppress", "Completed issue; no comment proposed.")
    # A private validity finding can remain supported while customer context is
    # incomplete. Delivery still requires the full mapped-field read coverage.
    missing = input_errors(ticket, require_customer_coverage=True)
    if missing:
        return decision("review_required", "; ".join(missing))
    if not ticket.comments_complete:
        return decision(
            "review_required", "Comment history is missing or truncated; fetch it in full."
        )
    body = packet.proposed_comment
    expected = recommendation_comment(packet, ticket)
    unsigned = body.removesuffix(comment_footer(marker)).removesuffix(
        f"Triage reference: `{marker}`."
    )
    if unsigned.rstrip() not in {expected, short_draft(packet)}:
        return decision(
            "review_required", "Draft does not match the verified recommendation and proof."
        )
    if re.search(r"\b(?:closing|will close)\b", body, re.I):
        return decision("review_required", "Comment claims a closure instead of recommending one.")
    citations = re.findall(r"\[[^\]]+\]\((https?://[^\s)]+)\)", body)
    allowed = {item.ref for item in packet.evidence if item.ref.startswith(("http://", "https://"))}
    allowed.update(
        f"https://redhat.atlassian.net/browse/{ref}"
        for ref in [ticket.key, packet.target, *[item.ref for item in packet.evidence]]
        if re.fullmatch(r"[A-Z][A-Z0-9_]+-\d+", ref)
    )
    # A target citation is useful only after the verdict policy selected it.
    if not citations or any(url not in allowed for url in citations):
        return decision(
            "review_required", "Comment needs linked evidence from the packet; check its citations."
        )
    unlinked = re.sub(r"\[[^\]]+\]\([^\s)]+\)", "", body)
    if re.search(r"https?://", unlinked):
        return decision("review_required", "Format the evidence URLs as Markdown links.")
    if re.search(r"\b(?:RHDHBUGS|RHIDP|RHDHPLAN|RHDHSUPP|ACCOUNT)-\d+\b", unlinked):
        return decision("review_required", "Link the Jira keys in the proposed comment.")
    reviewed = _history_review(ticket, assessment)
    if reviewed and (reviewed["equivalentAdvice"] or reviewed["pendingAction"]):
        return decision(
            "suppress",
            "The cited discussion review found equivalent advice or a pending action.",
            historyReview=reviewed,
        )
    prior = []
    for comment in ticket.comments:
        if "rhdh-bug-triage:" not in comment.body:
            continue
        matches = MARKER_RE.findall(comment.body)
        if len(matches) != 1:
            return decision(
                "review_required", "Unrecognized triage reference; reconcile history first."
            )
        created = parse_datetime(comment.created)
        if not created or not comment.id or created > as_of:
            return decision(
                "review_required", "Prior triage comment has no reliable ID or posting time."
            )
        prior.append((created, comment))
    unmarked = any("rhdh-bug-triage:" not in comment.body for comment in ticket.comments)
    if not prior and unmarked and not reviewed:
        return decision(
            "review_required",
            "Unmarked discussion needs a complete, cited historyReview before eligibility.",
        )
    if not prior:
        return decision(
            "propose",
            "Complete history has no previous equivalent advice or pending action; this draft is eligible for human review.",
            **({"historyReview": reviewed} if reviewed else {}),
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
    follow_up = assessment.follow_up if assessment and assessment.key == ticket.key else {}
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
            and valid_ref(item["ref"])
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
    if unmarked and not reviewed:
        return decision(
            "review_required",
            "Complete a cited historyReview of unmarked discussion before a changed recommendation.",
            **details,
        )
    return decision(
        "propose",
        "Cooldown elapsed and cited follow-up supports a changed recommendation.",
        followUp=follow_up,
        **({"historyReview": reviewed} if reviewed else {}),
        **details,
    )


def short_draft(packet: Packet) -> str:
    """Render the finding, one evidence link and the action. Keep the detailed basis in audit."""
    validation = packet.validation
    coverage_hold = next_step_kind(packet) == "verify_customer_coverage"
    trusted = not packet.verification_errors or coverage_hold
    finding = " ".join(str(validation.get("summary") or "").split()) if trusted else ""
    if len(finding) > 320:
        finding = finding.partition(". ")[0].rstrip(".") + "."
    if not finding or len(finding) > 320:
        finding = f"Triage result on {packet.current_release}: {packet.verdict.replace('_', ' ')}."
    cited = {item.ref for item in packet.evidence}
    ref = next((r for r in validation.get("refs", []) if trusted and r in cited), packet.key)
    link = "Evidence: " + ref_link(ref)
    if (
        (packet.verdict == "already_fixed" or coverage_hold)
        and packet.fix.get("merged")
        and packet.fix.get("pr") in cited
    ):
        link = "Fix: " + ref_link(packet.fix["pr"])
    elif packet.verdict == "duplicate":
        link = "Canonical issue: " + ref_link(packet.target)
    action = packet.recommended_step
    if trusted and packet.investigation.get("status") == "blocked":
        action = _linked_text(packet.investigation.get("blocker") or "") or action
    return "\n".join([_linked_text(finding), link, action])


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
    if packet.proposed_comment:
        packet.proposed_comment = short_draft(packet)
        packet.proposed_comment += "\n\n" + comment_footer(packet.comment_plan["reference"])
