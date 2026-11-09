"""Markdown, CSV, and JSON rendering for a bug-triage run.

Every artifact carries the dry-run statement. The report is written to a local
directory chosen by the caller; nothing in this module opens a network
connection or invokes a Jira mutation.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .model import Ticket, age_days, age_label
from .policy import Packet

DRY_RUN_BANNER = (
    "**Dry run.** Nothing in this artifact was posted, transitioned, linked, or "
    "written to Jira. Every proposed action is local and requires a human gate."
)

ACTION_LABELS = {
    "propose_close_duplicate": "Close as duplicate",
    "propose_close_fixed": "Close as fixed",
    "propose_close_obsolete": "Close as no longer valid",
    "comment_only": "Comment only",
    "keep_open": "Keep open",
    "needs_repro": "Ask for reproduction",
    "unclear": "No action",
}


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _pct(part: int, total: int) -> str:
    if not total:
        return "n/a"
    return f"{100 * part / total:.0f}%"


def _confidence(value: float) -> str:
    return f"{value:.2f}"


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
    days = age_days(ticket.created, as_of)
    lines = [
        f"# {packet.key} — {packet.summary.strip() or '(no summary)'}",
        "",
        DRY_RUN_BANNER,
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Status | {_cell(packet.status or 'unknown')} |",
        f"| Kind | {_cell(kind + (f' ({control_label})' if control_label else ''))} |",
        f"| Age | {_cell(age_label(days))} |",
        f"| Team | {_cell(ticket.team or 'unset')} |",
        f"| Components | {_cell(', '.join(ticket.components) or 'unset')} |",
        f"| Assignee | {_cell(ticket.assignee or 'unassigned')} |",
        f"| Priority | {_cell(ticket.priority or 'unset')} |",
        f"| Current release | {_cell(packet.current_release)} |",
        f"| Disposition | `{packet.disposition}` |",
        f"| Confidence | {_confidence(packet.confidence)} |",
        f"| Action | `{packet.action}` — {ACTION_LABELS.get(packet.action, packet.action)} |",
        f"| Target | {_cell(packet.target or '—')} |",
        "| Human gate | required before any write |",
        "",
        "## Recommendation",
        "",
        packet.recommended_step or "Review the evidence.",
        "",
        "## Confidence basis",
        "",
    ]
    if packet.confidence_basis:
        lines.extend(f"- {item}" for item in packet.confidence_basis)
    else:
        lines.append("- no evidence")

    lines.extend(["", "## Evidence", ""])
    if packet.evidence:
        lines.extend(
            [
                "| Strength | Type | Reference | Why it matters |",
                "|---|---|---|---|",
            ]
        )
        for item in packet.evidence:
            lines.append(
                f"| {_cell(item.strength)} | {_cell(item.type)} | {_cell(item.ref)} | "
                f"{_cell(item.why)} |"
            )
    else:
        lines.append("No cited evidence was supplied.")

    lines.extend(["", "## Duplicate candidates", ""])
    if packet.duplicate_candidates:
        lines.extend(
            [
                "| Score | Ticket | Status | Reasons |",
                "|---|---|---|---|",
            ]
        )
        for candidate in packet.duplicate_candidates:
            lines.append(
                f"| {candidate.score:.2f} | {candidate.key} | {_cell(candidate.status)} | "
                f"{_cell('; '.join(candidate.reasons))} |"
            )
    else:
        lines.append("No candidate above the retrieval floor.")

    lines.extend(["", "## Gaps and guardrails", ""])
    combined = list(packet.gaps)
    if packet.customer_signals:
        combined.append("Customer signals: " + ", ".join(packet.customer_signals))
    if packet.verification_errors:
        combined.extend(f"Verifier: {error}" for error in packet.verification_errors)
    if combined:
        lines.extend(f"- {item}" for item in combined)
    else:
        lines.append("- none recorded")

    if packet.proposed_comment.strip():
        lines.extend(
            [
                "",
                "## Proposed Jira comment (not posted)",
                "",
                "```text",
                packet.proposed_comment.strip(),
                "```",
            ]
        )
    else:
        lines.extend(["", "## Proposed Jira comment", "", "No comment proposed."])

    if generated_at:
        lines.extend(["", f"Generated {generated_at} by `rhdh-bug-triage`."])
    return "\n".join(lines) + "\n"


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
) -> str:
    total = len(packets)
    decision_ready = sum(1 for packet in packets if packet.action != "unclear")
    classified = sum(
        1 for packet in packets if packet.disposition not in ("unclear", "needs_repro")
    )
    close_proposals = sum(1 for packet in packets if packet.action.startswith("propose_close"))
    customer = sum(1 for packet in packets if packet.customer_signals)
    with_evidence = sum(1 for packet in packets if packet.evidence)
    gaps = sum(len(packet.gaps) for packet in packets)

    disposition_counts: Dict[str, int] = {}
    action_counts: Dict[str, int] = {}
    for packet in packets:
        disposition_counts[packet.disposition] = disposition_counts.get(packet.disposition, 0) + 1
        action_counts[packet.action] = action_counts.get(packet.action, 0) + 1

    lines = [
        "# RHDH aged-bug triage report",
        "",
        DRY_RUN_BANNER,
        "",
        f"Generated {generated_at} · as of {as_of.date().isoformat()} · "
        f"current release **{current_release}**.",
        "",
        "## Run at a glance",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Tickets in report | {total} |",
        f"| Aged sample | {sample_size} |",
        f"| Controls | {control_count} |",
        f"| Corpus available for duplicate retrieval | {corpus_size} |",
        f"| Decision-ready | {decision_ready}/{total} ({_pct(decision_ready, total)}) |",
        f"| Classified disposition | {classified}/{total} ({_pct(classified, total)}) |",
        f"| Packets with cited evidence | {with_evidence}/{total} ({_pct(with_evidence, total)}) |",
        f"| Close proposals (local only) | {close_proposals} |",
        f"| Customer-linked tickets in report | {customer} |",
        f"| Recorded evidence gaps | {gaps} |",
        "",
        "## Dispositions",
        "",
        "| Disposition | Count |",
        "|---|---|",
    ]
    for name in sorted(disposition_counts):
        lines.append(f"| `{name}` | {disposition_counts[name]} |")
    lines.extend(["", "## Actions", "", "| Action | Count |", "|---|---|"])
    for name in sorted(action_counts):
        lines.append(f"| `{name}` | {action_counts[name]} |")

    lines.extend(
        [
            "",
            "## Sample",
            "",
            "| Key | Kind | Age | Team | Disposition | Conf | Action | Evidence |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for packet in packets:
        selection_entry = selection.get(packet.key, {})
        ticket = tickets[packet.key]
        kind = str(selection_entry.get("kind", "aged"))
        if selection_entry.get("controlLabel"):
            kind += f" ({selection_entry['controlLabel']})"
        evidence_line = packet.evidence[0].why if packet.evidence else "—"
        lines.append(
            f"| {packet.key} | {_cell(kind)} | {age_label(age_days(ticket.created, as_of))} | "
            f"{_cell(selection_entry.get('stratum', ticket.team or 'unset'))} | "
            f"`{packet.disposition}` | {_confidence(packet.confidence)} | "
            f"`{packet.action}` | {_cell(evidence_line)} |"
        )

    lines.extend(["", "## Method", ""])
    lines.extend(
        [
            f"- Selection JQL: `{jql}`",
            f"- Customer filter: labels {sorted(set(['RHDH-Customer']))}, links to "
            "RHDHSUPP/ACCOUNT, and the customer/support fields; any hit excludes the "
            "ticket and disables a close proposal.",
            "- Duplicate retrieval: deterministic lexical similarity over summary, "
            "description, error signatures, components, and explicit links; the top "
            "candidates are shown for human adjudication.",
            "- Confidence is evidence-based: direct = 1.0, strong = 0.8, supporting = 0.5, "
            "plus a small bonus for independent citations. The model does not supply a "
            "confidence number.",
            f"- Close thresholds: duplicate {thresholds['duplicate']:.2f}, fixed "
            f"{thresholds['fixed']:.2f}, obsolete {thresholds['obsolete']:.2f}. A close "
            "also requires direct evidence and two agreeing independent passes.",
            "- Posting, transitions, links, and field writes are out of scope. A human "
            "hands an approved proposal to `/rhdh-jira-update`, which applies "
            "`/mutation-gate`.",
        ]
    )

    if excluded:
        lines.extend(["", "## Excluded from the sample", ""])
        for item in excluded[:50]:
            lines.append(f"- {item['key']}: {item['reason']}")
        if len(excluded) > 50:
            lines.append(f"- … and {len(excluded) - 50} more")

    lines.extend(["", "## Per-ticket packets", ""])
    for packet in packets:
        ticket = tickets[packet.key]
        lines.extend(
            [
                f"### {packet.key} — {packet.summary.strip() or '(no summary)'}",
                "",
                f"- Disposition: `{packet.disposition}` at {packet.confidence:.2f}",
                f"- Action: `{packet.action}`" + (f" → {packet.target}" if packet.target else ""),
                f"- Recommendation: {packet.recommended_step}",
                f"- Evidence: {len(packet.evidence)} cited item(s)"
                + (
                    f"; first: {packet.evidence[0].why} ({packet.evidence[0].ref})"
                    if packet.evidence
                    else ""
                ),
            ]
        )
        if packet.gaps:
            lines.append("- Gaps: " + "; ".join(packet.gaps))
        if packet.proposed_comment.strip():
            lines.append(f"- Proposed comment: `proposed/{packet.key}.md`")
        lines.append("")

    lines.extend(
        [
            "## Limits",
            "",
            "- A deterministic score is a retrieval aid, not a duplicate verdict. The "
            "packet shows the candidates; a human confirms meaning.",
            "- A missing affects or fix version is recorded as a data gap, not read as "
            "evidence that the bug is old or fixed.",
            "- Code inspection and reproduction are optional inputs. When they are absent, "
            "the packet says `needs_repro` rather than guessing.",
            "- This report makes no claim about customer impact beyond the customer "
            "signals it lists.",
            "",
        ]
    )
    return "\n".join(lines)


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
    sample_size: int,
    control_count: int,
    packets: List[Packet],
    thresholds: Dict[str, float],
    policy_version: int,
) -> Dict[str, Any]:
    return {
        "schemaVersion": 1,
        "dryRun": True,
        "generatedAt": generated_at,
        "asOf": as_of.date().isoformat(),
        "currentRelease": current_release,
        "policyVersion": policy_version,
        "inputs": {
            "export": input_path,
            "sample": sample_path,
            "assessments": assessments_path,
        },
        "output": output_path,
        "jql": jql,
        "corpusSize": corpus_size,
        "sampleSize": sample_size,
        "controlCount": control_count,
        "thresholds": thresholds,
        "counts": {
            "packets": len(packets),
            "withEvidence": sum(1 for packet in packets if packet.evidence),
            "closeProposals": sum(
                1 for packet in packets if packet.action.startswith("propose_close")
            ),
            "customerLinked": sum(1 for packet in packets if packet.customer_signals),
        },
        "writes": [],
        "writePolicy": "read-only; proposed actions live under proposed/ and are never posted",
    }


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
