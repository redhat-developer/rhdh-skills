"""Exact dry-run comment previews, with decisions separate from delivery."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .model import Ticket
from .policy import CLOSE_ACTIONS, Packet

DRY_RUN_BANNER = (
    "**Dry run.** Nothing was posted, transitioned, linked, or written to Jira. "
    "No bugs were closed and no PRs were created. Comments below are previews, not posting receipts."
)


def surfaced(packet: Packet) -> bool:
    return bool(packet.proposed_comment)


def _delivery(packet: Packet) -> List[str]:
    plan = packet.comment_plan
    if not plan:
        return []
    return [f"**Comment delivery:** `{plan['status']}` — {plan['reason']}", ""]


def render_packet(
    packet: Packet,
    ticket: Ticket,
    *,
    kind: str = "aged",
    stratum: str = "",
    control_label: str = "",
    as_of: Optional[datetime] = None,
    generated_at: Optional[str] = None,
) -> str:
    if not surfaced(packet):
        return ""
    lines = [
        packet.proposed_comment,
        "",
        "---",
        "",
        "## Review details",
        "",
        DRY_RUN_BANNER,
        "",
        f"**Action:** `{packet.action}` · **Human gate:** required",
        "",
        f"**Owner:** {ticket.team or 'not established'}; {ticket.assignee or 'unassigned'}.",
        "",
        f"**Release under review:** {packet.current_release}.",
        "",
        f"**Sample:** {kind}" + (f" ({control_label})" if control_label else "") + ".",
        "",
        *_delivery(packet),
    ]
    if packet.notes:
        lines += [f"**Review note:** {packet.notes}", ""]
    if packet.gaps:
        lines += ["**Audit gaps:**", *[f"- {gap}" for gap in packet.gaps], ""]
    if generated_at:
        lines += [f"Generated {generated_at}.", ""]
    return "\n".join(lines)


def render_report(
    packets: List[Packet],
    tickets: Dict[str, Ticket],
    *,
    generated_at: str,
    as_of: datetime,
    current_release: str,
    jql: str,
    sample_size: int,
    control_count: int,
    corpus_size: int,
    excluded: List[Dict[str, str]],
    selection: Dict[str, Dict[str, Any]],
    thresholds: Dict[str, float],
    corpus_has_closed: bool = True,
    coverage: Optional[Dict[str, Any]] = None,
    release_evidence: str = "",
) -> str:
    coverage = coverage or {}
    drafts = sum(surfaced(p) for p in packets)
    delivery = {
        status: sum(p.comment_plan.get("status") == status for p in packets)
        for status in ("propose", "review_required", "suppress")
    }
    lines = [
        f"# RHDH bug triage — {as_of.date().isoformat()}",
        "",
        DRY_RUN_BANNER,
        "",
        "Each triaged issue appears below, including uncertainty. A draft is not permission to post. "
        "Suppressed drafts are shown for inspection only; they must not be sent again.",
        "",
        f"**Bottom line:** {len(packets)} triaged; {drafts} comment draft(s); "
        f"{sum(p.action in CLOSE_ACTIONS for p in packets)} advisory closure recommendation(s).",
        "",
        f"- Delivery: {delivery['propose']} proposed; {delivery['review_required']} require history/proof review; {delivery['suppress']} suppressed.",
        f"- Reviewed: {len(packets)} ({control_count} Control tickets). Scope: {coverage.get('scope', 'aged')}.",
        f"- Corpus: {corpus_size} tickets; release under review: {current_release}.",
        f"- Product release evidence: {release_evidence or 'not supplied'}.",
        f"- Selection: {coverage.get('selectedIssues', len(packets))} of {coverage.get('eligibleIssues', 'unknown')} eligible; {len(excluded)} excluded with reasons in sample.json.",
        "- Corpus retrieval is bounded unless its source proves otherwise; including some closed tickets is not exhaustive coverage.",
        "",
        "## Exact comment previews",
        "",
    ]
    if not packets:
        lines += [
            "No issues matched the eligibility rules. No issues were silently marked triaged.",
            "",
        ]
    for packet in packets:
        ticket = tickets[packet.key]
        lines += [
            f"### {packet.key} — {packet.summary}",
            "",
            f"**Owner:** {ticket.team or 'not established'}; {ticket.assignee or 'unassigned'}.",
            "",
            *_delivery(packet),
        ]
        if packet.proposed_comment:
            lines += [f"> {line}" if line else ">" for line in packet.proposed_comment.splitlines()]
        else:
            lines += ["No comment draft: customer/completed/ineligible issue or unsafe inputs."]
        lines += [
            "",
            "**Dry-run restriction:** do not post this preview. Any later approved handoff is comment-only; "
            "transitions, closures, fixes, PRs, and backports are out of scope.",
            "",
        ]
        if packet.notes:
            lines += [f"**Reviewer context:** {packet.notes}", ""]
        if packet.gaps:
            lines += ["**Limits:** " + "; ".join(packet.gaps), ""]
        collected = coverage.get("collection", {}).get(packet.key, {})
        if collected:
            searches = collected.get("searches", [])
            failures = sum(s.get("status") != "success" for s in searches)
            lines += [
                f"**Forge coverage:** {collected.get('searchMode', 'unknown')}; {len(searches)} queries, {failures} failed/invalid. Failed queries are not zero matches.",
                "",
            ]
        lines += ["---", ""]
    lines += [
        "## Method and limits",
        "",
        f"- Selection query: `{jql}`.",
        f"- Close thresholds: duplicate {thresholds['duplicate']:.2f}; already fixed {thresholds['fixed']:.2f}.",
        "- Closure advice needs cited claim-by-claim proof and two agreeing independent reviews. "
        "Similarity and a high score alone are insufficient.",
        "- Duplicate canonical selection uses actual creation timestamps, not key order or recency. "
        "Newer or undated canonical targets require separate human selection and are not proposed here.",
        "- A fix must cover the whole reported failure, be merged/incorporated, and have direct released-inclusion evidence "
        "no newer than the release under review. Partial or unreleased fixes are not recommendations.",
        "- Confidence is a citation-strength policy score, not a calibrated probability or a guarantee. "
        "Reviewers must read the cited artifacts; code inspection is not a runtime reproduction.",
        "- Open status and lack of a fix search hit do not prove a bug still exists. Still-valid/obsolete claims need exact-release validation.",
        "- Customer-linked and completed issues cannot receive automated comments.",
        "- Suppression is a no-op, not a reminder or a reason to notify anyone.",
        "- Missing data and disagreement are reported as uncertainty, not silently hidden. No generic reproduction pings or reminders.",
        "- Assessments are agent judgments over cited snapshots. Structural checks and independent reviewers do not guarantee factual correctness or 100% accuracy.",
        f"- Generated {generated_at}; no external writes.",
    ]
    lines.append(
        "- Duplicate retrieval included open and closed reports."
        if corpus_has_closed
        else "- The corpus has **no closed tickets**: closed canonical reports were unreachable. "
        "Use a broader open-and-closed export; absence of a match is not evidence of uniqueness."
    )
    if excluded:
        lines += [f"- {len(excluded)} selection exclusion(s) are recorded in the sample manifest."]
    return "\n".join(lines) + "\n"


def render_summary_csv(packets: List[Packet], selection: Dict[str, Dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "key",
            "kind",
            "controlLabel",
            "stratum",
            "status",
            "disposition",
            "confidence",
            "action",
            "target",
            "recommendedStep",
            "evidenceCount",
            "gapCount",
            "customerLinked",
        ]
    )
    for packet in packets:
        entry = selection.get(packet.key, {})
        writer.writerow(
            [
                packet.key,
                entry.get("kind", "aged"),
                entry.get("controlLabel", ""),
                entry.get("stratum", ""),
                packet.status,
                packet.disposition,
                f"{packet.confidence:.2f}",
                packet.action,
                packet.target,
                packet.recommended_step,
                len(packet.evidence),
                len(packet.gaps),
                "yes" if packet.customer_signals else "no",
            ]
        )
    return buffer.getvalue()


def render_manifest(
    *,
    generated_at: str,
    as_of: datetime,
    current_release: str,
    jql: str,
    input_path: str,
    sample_path: str,
    assessments_path: str,
    output_path: str,
    corpus_size: int,
    corpus_has_closed: bool = True,
    sample_size: int,
    control_count: int,
    packets: List[Packet],
    thresholds: Dict[str, float],
    policy_version: int,
) -> Dict[str, Any]:
    return {
        "schemaVersion": 3,
        "dryRun": True,
        "generatedAt": generated_at,
        "asOf": as_of.date().isoformat(),
        "currentRelease": current_release,
        "policyVersion": policy_version,
        "inputs": {"export": input_path, "sample": sample_path, "assessments": assessments_path},
        "output": output_path,
        "jql": jql,
        "corpusSize": corpus_size,
        "corpusHasClosed": corpus_has_closed,
        "sampleSize": sample_size,
        "controlCount": control_count,
        "thresholds": thresholds,
        "counts": {
            "packets": len(packets),
            "withEvidence": sum(bool(p.evidence) for p in packets),
            "draftComments": sum(bool(p.proposed_comment) for p in packets),
            "closeProposals": sum(p.action in CLOSE_ACTIONS for p in packets),
            "surfacedRecommendations": sum(surfaced(p) for p in packets),
            "abstained": sum(p.action == "abstain" for p in packets),
            "customerLinked": sum(bool(p.customer_signals) for p in packets),
        },
        "writes": [],
        "writePolicy": "dry-run comment previews only; no Jira mutations, closures, PRs or backports",
    }


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
