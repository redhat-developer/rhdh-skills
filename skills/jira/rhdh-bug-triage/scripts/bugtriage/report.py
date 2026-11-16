"""Recommendation-only reports; abstentions stay in the local structured audit."""

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
    "Closure recommendations require human approval."
)


def surfaced(packet: Packet) -> bool:
    return (
        packet.action in CLOSE_ACTIONS
        and bool(packet.proposed_comment)
        and packet.comment_plan.get("status") != "suppress"
    )


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
) -> str:
    recommendations = [p for p in packets if surfaced(p)]
    abstained = sum(p.action == "abstain" for p in packets)
    suppressed = sum(p.action in CLOSE_ACTIONS and not surfaced(p) for p in packets)
    duplicates = sum(p.disposition == "duplicate" for p in recommendations)
    fixed = len(recommendations) - duplicates
    lines = [
        f"# RHDH closure recommendations — {as_of.date().isoformat()}",
        "",
        DRY_RUN_BANNER,
        "",
        "**Everything needed to review the recommendations is in this file.** "
        "Only high-confidence duplicate and already-fixed findings are surfaced; "
        "other issues are left unchanged without a comment or reproduction request.",
        "",
        f"**Bottom line:** {duplicates} duplicate and {fixed} already-fixed recommendation(s); "
        f"{abstained} issue(s) left unchanged; {suppressed} repeat/ineligible recommendation(s) suppressed.",
        "",
        f"- Reviewed: {len(packets)} ({sample_size} aged; {control_count} Control tickets).",
        f"- Corpus: {corpus_size} tickets; release under review: {current_release}.",
        "- No proposed comment or handoff file is produced for an abstention.",
        "",
        "## Recommendations",
        "",
    ]
    if not recommendations:
        lines += [
            "No new closure recommendation met the evidence and delivery gates. "
            "Nothing needs approval; Jira remains unchanged. This is not proof that "
            "the remaining issues are unique or unfixed.",
            "",
        ]
    for packet in recommendations:
        ticket = tickets[packet.key]
        lines += [
            f"### {packet.key} — {packet.summary}",
            "",
            f"**Owner:** {ticket.team or 'not established'}; {ticket.assignee or 'unassigned'}.",
            "",
            *_delivery(packet),
        ]
        lines += [f"> {line}" if line else ">" for line in packet.proposed_comment.splitlines()]
        lines += [
            "",
            "**Approval:** review the proof, then hand the exact approved recommendation "
            "to `/rhdh-jira-update` under `/mutation-gate`; this run executes neither operation.",
            "",
        ]
        if packet.notes:
            lines += [f"**Reviewer context:** {packet.notes}", ""]
        lines += ["---", ""]
    lines += [
        "## Method and limits",
        "",
        f"- Selection query: `{jql}`.",
        f"- Close thresholds: duplicate {thresholds['duplicate']:.2f}; already fixed {thresholds['fixed']:.2f}.",
        "- Every recommendation needs cited claim-by-claim proof and two agreeing independent reviews. "
        "Similarity and a high score alone are insufficient.",
        "- Duplicate canonical selection uses actual creation timestamps, not key order or recency. "
        "Newer or undated canonical targets require separate human selection and are not proposed here.",
        "- A fix must cover the whole reported failure, be merged/incorporated, and have direct released-inclusion evidence "
        "no newer than the release under review. Partial or unreleased fixes are not recommendations.",
        "- Confidence is a citation-strength policy score, not a calibrated probability or a guarantee. "
        "Reviewers must read the cited artifacts; code inspection is not a runtime reproduction.",
        "- Customer-linked and completed issues cannot receive closure recommendations.",
        "- Suppression is a no-op, not a reminder or a reason to notify anyone.",
        "- Abstention reasons, internal evidence states, candidates, rejected proof, and suppressed drafts "
        "are retained only in the local `packets.json` / `summary.csv` audit. "
        "They are not requests for a human to investigate every issue.",
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
        "schemaVersion": 2,
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
            "closeProposals": sum(p.action in CLOSE_ACTIONS for p in packets),
            "surfacedRecommendations": sum(surfaced(p) for p in packets),
            "abstained": sum(p.action == "abstain" for p in packets),
            "customerLinked": sum(bool(p.customer_signals) for p in packets),
        },
        "writes": [],
        "writePolicy": "read-only; only qualifying recommendations have proposed/ handoff files",
    }


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
