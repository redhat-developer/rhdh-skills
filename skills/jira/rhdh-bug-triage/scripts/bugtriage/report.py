"""Markdown, CSV, and JSON rendering for a bug-triage run.

Every artifact carries the dry-run statement. The report is written to a local
directory chosen by the caller; nothing in this module opens a network
connection or invokes a Jira mutation.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .model import Ticket, age_days, age_label
from .policy import Packet, ref_link

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
    context = " \u00b7 ".join(
        [
            packet.status or "unknown status",
            age_label(days),
            ticket.team or "team unset",
            ", ".join(ticket.components) or "components unset",
            ticket.assignee or "unassigned",
            f"release {packet.current_release}",
            kind + (f" ({control_label})" if control_label else ""),
        ]
    )

    lines = [
        f"# {packet.key} \u2014 {packet.summary.strip() or '(no summary)'}",
        "",
        "> **Dry run.** This is the exact comment that would be posted to "
        f"{ref_link(packet.key)}. Nothing was posted, transitioned, linked, or written "
        "to Jira.",
        "",
        "## Comment",
        "",
    ]
    comment = packet.proposed_comment.strip()
    lines.append(comment if comment else "_No comment proposed._")

    lines.extend(
        [
            "",
            "---",
            "",
            "## Review details",
            "",
            f"**Action:** `{packet.action}` — "
            f"{ACTION_LABELS.get(packet.action, packet.action)} \u00b7 "
            f"**Disposition:** `{packet.disposition}` \u00b7 "
            f"**Confidence:** {_confidence(packet.confidence)} \u00b7 "
            "**Human gate:** required",
            "",
            f"**Context.** {context}",
            "",
            f"**Why this comment.** {packet.recommended_step or 'Review the evidence.'}",
        ]
    )
    if packet.target:
        lines.extend(["", f"**Target.** {ref_link(packet.target)}"])
    if packet.notes:
        lines.extend(["", f"**Notes.** {' '.join(packet.notes.split())}"])
    basis = "; ".join(packet.confidence_basis) or "no evidence basis recorded"
    lines.extend(["", f"**Confidence basis.** {basis}"])

    lines.extend(["", "**Evidence**", ""])
    if packet.evidence:
        for item in packet.evidence:
            why = " ".join(item.why.split())
            lines.append(f"- `{item.strength}` {ref_link(item.ref)} \u2014 {why}")
    else:
        lines.append("- no cited evidence")

    if packet.duplicate_candidates:
        lines.extend(["", "**Duplicate candidates**", ""])
        for candidate in packet.duplicate_candidates:
            reasons = " ".join("; ".join(candidate.reasons).split())
            lines.append(f"- {ref_link(candidate.key)} {candidate.score:.2f} \u2014 {reasons}")

    combined = list(packet.gaps)
    if packet.customer_signals:
        combined.append("Customer signals: " + ", ".join(packet.customer_signals))
    if packet.verification_errors:
        combined.extend(f"Verifier: {error}" for error in packet.verification_errors)
    lines.extend(["", "**Gaps and guardrails**", ""])
    if combined:
        lines.extend(f"- {item}" for item in combined)
    else:
        lines.append("- none recorded")

    if generated_at:
        lines.extend(["", f"Generated {generated_at} by `rhdh-bug-triage`."])
    return "\n".join(lines) + "\n"


DISPOSITION_LABELS = {
    "duplicate": "Duplicate",
    "already_fixed": "Already fixed",
    "still_valid": "Still valid",
    "no_longer_valid": "No longer valid",
    "needs_repro": "Needs reproduction",
    "unclear": "Unclear",
}


def _short(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\u2026"


URL_RE = re.compile(r"https?://[^\s<>\])]+")
PR_URL_RE = re.compile(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)")
RELEASE_URL_RE = re.compile(r"https://github\.com/([^/]+/[^/]+)/releases/tag/([^\s<>\])]+)")


def _url_label(url: str) -> str:
    pr = PR_URL_RE.match(url)
    if pr:
        return f"PR #{pr.group(2)}"
    release = RELEASE_URL_RE.match(url)
    if release:
        return release.group(2)
    if "atlassian.net/browse/" in url:
        return url.rsplit("/", 1)[-1]
    return url if len(url) <= 50 else _short(url, 47)


def _linkify(text: str) -> str:
    """Turn bare URLs into Markdown links with a readable label."""

    def replace(match: re.Match) -> str:
        url = match.group(0).rstrip(".,;:")
        return f"[{_url_label(url)}]({url})"

    return URL_RE.sub(replace, text)


def _verdict(packet: Packet) -> str:
    label = DISPOSITION_LABELS.get(packet.disposition, packet.disposition)
    closing = packet.action.startswith("propose_close")
    if packet.disposition == "duplicate":
        base = f"Duplicate of {packet.target}" if packet.target else "Duplicate"
        return base if closing else f"Possible {base[0].lower() + base[1:]}"
    if packet.disposition == "unclear" and packet.action == "needs_repro":
        return "Needs reproduction"
    if not closing and packet.disposition in ("already_fixed", "no_longer_valid"):
        return f"Possibly {label[0].lower() + label[1:]}"
    return label


def _why(packet: Packet) -> str:
    if packet.evidence:
        return packet.evidence[0].why
    if packet.disposition == "unclear":
        return "No assessment reached a confident disposition."
    return "No cited evidence yet."


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
    total = len(packets)
    decision_ready = sum(1 for packet in packets if packet.action != "unclear")
    with_evidence = sum(1 for packet in packets if packet.evidence)
    gaps = sum(len(packet.gaps) for packet in packets)
    close_proposals = [p for p in packets if p.action.startswith("propose_close")]
    needs_repro = sum(1 for p in packets if p.action == "needs_repro")
    keep_open = sum(1 for p in packets if p.action == "keep_open")
    comment_only = sum(1 for p in packets if p.action == "comment_only")
    no_action = sum(1 for p in packets if p.action == "unclear")
    customer = sum(1 for p in packets if p.customer_signals)

    outcome = []
    if close_proposals:
        outcome.append(
            f"{len(close_proposals)} can be closed once you approve the proposed comment"
        )
    else:
        outcome.append("no ticket passed the close gates")
    if keep_open:
        outcome.append(f"{keep_open} should stay open")
    if needs_repro:
        outcome.append(f"{needs_repro} need{'s' if needs_repro == 1 else ''} a reproduction")
    if comment_only:
        verb = "warrants" if comment_only == 1 else "warrant"
        outcome.append(f"{comment_only} {verb} a comment only")
    if no_action:
        outcome.append(f"{no_action} {'is' if no_action == 1 else 'are'} unclear")
    bottom_line = "; ".join(outcome) + "."

    def boolean(value: int, singular: str, plural: str) -> str:
        return f"{value} {singular if value == 1 else plural}"

    sampled = boolean(sample_size, "aged ticket", "aged tickets")
    if control_count:
        sampled += " and " + boolean(control_count, "control", "controls")

    lines = [
        f"# RHDH aged-bug triage \u2014 {as_of.date().isoformat()}",
        "",
        DRY_RUN_BANNER,
        "",
        "**Everything a reviewer needs is in this file.** It opens with the numbers, "
        "then gives one section per ticket: the verdict, the evidence behind it, the "
        "next step, and the exact comment that would be posted. Nothing here is a "
        "close until a human approves it.",
        "",
        f"**Bottom line.** {bottom_line[0].upper() + bottom_line[1:]}",
        "",
        "## The numbers",
        "",
        f"- **Sampled:** {sampled}.",
        f"- **Corpus searched:** {corpus_size} tickets"
        + (", including closed reports." if corpus_has_closed else ", with no closed reports."),
        f"- **Release under review:** {current_release}.",
        f"- **Can close now:** {len(close_proposals)}.",
        f"- **Keep open:** {keep_open}.",
        f"- **Need a reproduction:** {needs_repro}.",
        f"- **Comment only:** {comment_only}.",
        f"- **Unclear:** {no_action}.",
        f"- **Decision-ready:** {decision_ready} of {total}.",
        f"- **Tickets with cited evidence:** {with_evidence} of {total}.",
        f"- **Evidence gaps:** {gaps} across the sample.",
        "",
        "## Close proposals",
        "",
    ]
    if close_proposals:
        for packet in close_proposals:
            lines.extend(
                [
                    f"**{packet.key} \u2014 {_verdict(packet)}.** "
                    f"{_linkify(packet.recommended_step)}",
                    "",
                    "The exact comment is in this file, under this ticket's own heading below.",
                    "",
                ]
            )
    else:
        lines.extend(
            [
                "No ticket passed the close gates, so nothing is waiting for a close "
                "decision. Every ticket still carries its own proposed comment below.",
                "",
            ]
        )

    if customer:
        lines.extend(
            [
                "## Customer-linked",
                "",
                f"{boolean(customer, 'ticket carries', 'tickets carry')} a customer signal "
                "and cannot be closed by this skill.",
                "",
            ]
        )

    lines.extend(["## The tickets", ""])
    for packet in packets:
        ticket = tickets.get(packet.key)
        days = age_days(ticket.created, as_of) if ticket else None
        context = " \u00b7 ".join(
            [
                packet.status or "unknown status",
                age_label(days),
                (ticket.team if ticket else "") or "team unset",
                ", ".join(ticket.components)
                if ticket and ticket.components
                else "components unset",
                (ticket.assignee if ticket else "") or "unassigned",
            ]
        )
        why = " ".join(_why(packet).split())
        score = (
            f"Confidence {_confidence(packet.confidence)}."
            if packet.evidence or packet.confidence > 0
            else "Not scored yet."
        )
        lines.extend(
            [
                f"### {packet.key} \u2014 {packet.summary.strip() or '(no summary)'}",
                "",
                f"**{_verdict(packet)}.** {score} {context}.",
                "",
                _linkify(why[0].upper() + why[1:]) if why else "",
                "",
                f"**Do this next:** {_linkify(packet.recommended_step or 'Review the evidence.')}",
                "",
                "**Proposed comment** (local only, never posted):",
                "",
            ]
        )
        comment = packet.proposed_comment.strip()
        if comment:
            lines.extend(f"> {line}" if line else ">" for line in comment.splitlines())
        else:
            lines.append("> _No comment proposed._")
        lines.append("")

        if packet.target:
            lines.extend([f"**Target:** {ref_link(packet.target)}", ""])

        if packet.evidence:
            lines.extend(["**Evidence**", ""])
            for item in packet.evidence:
                ref = (
                    _linkify(item.ref)
                    if item.ref.startswith(("http://", "https://"))
                    else ref_link(item.ref)
                )
                lines.append(f"- `{item.strength}` {ref} \u2014 {' '.join(item.why.split())}")
            lines.append("")
        else:
            lines.extend(["**Evidence:** none cited yet.", ""])

        if packet.duplicate_candidates:
            lines.extend(["**Possible duplicates**", ""])
            for candidate in packet.duplicate_candidates:
                reasons = " ".join("; ".join(candidate.reasons).split())
                lines.append(f"- {ref_link(candidate.key)} {candidate.score:.2f} \u2014 {reasons}")
            lines.append("")

        combined = list(packet.gaps)
        if packet.customer_signals:
            combined.append("Customer signals: " + ", ".join(packet.customer_signals))
        if packet.verification_errors:
            combined.extend(f"Verifier: {error}" for error in packet.verification_errors)
        if combined:
            lines.extend(["**Gaps and guardrails**", ""])
            lines.extend(f"- {item}" for item in combined)
            lines.append("")
        if packet.notes:
            lines.extend([f"**Review note:** {' '.join(packet.notes.split())}", ""])
        lines.extend(["---", ""])

    lines.extend(
        [
            "## How this was decided",
            "",
            f"- Selection query: `{jql}`",
            "- Selection excludes customer-linked tickets, anything already Done, and "
            "anything younger than the aged threshold. Controls are appended deliberately.",
        ]
    )
    if corpus_has_closed:
        lines.append(
            "- Duplicate retrieval searched open **and closed** tickets in the corpus, so a "
            "closed canonical report was reachable."
        )
    else:
        lines.append(
            "- Duplicate retrieval had **no closed tickets** in the corpus, so a closed "
            "canonical report could not be found. Export `project = RHDHBUGS` (or open plus "
            "recently resolved) and rerun to close that gap."
        )
    lines.extend(
        [
            "- Duplicate scoring uses summary, description, error signatures, components, "
            "and Jira links. It ranks candidates; it never declares a duplicate on its own.",
            f"- Close thresholds: duplicate {thresholds['duplicate']:.2f}, fixed "
            f"{thresholds['fixed']:.2f}, no-longer-valid {thresholds['obsolete']:.2f}. A "
            "close also needs direct evidence and two agreeing independent passes.",
            "- Confidence comes from evidence strength, never from the model: direct 1.00, "
            "strong 0.80, supporting 0.50.",
            f"- Generated {generated_at} by the read-only triage pass.",
            "- Nothing was written: no comment, transition, link, or field change.",
        ]
    )

    if excluded:
        lines.extend(["", "## Not in the sample", ""])
        for item in excluded[:10]:
            lines.append(f"- {item['key']}: {_short(item['reason'], 120)}")
        if len(excluded) > 10:
            lines.append(f"- \u2026 and {len(excluded) - 10} more (see `manifest.json`)")

    lines.extend(
        [
            "",
            "## Limits",
            "",
            "- A deterministic score is a retrieval aid, not a duplicate verdict.",
            "- A missing affects or fix version is a data gap, not proof that the bug is old "
            "or fixed.",
            "- Code inspection and reproduction are optional inputs. Without them the verdict "
            "is `needs_repro`, not a guess.",
            "- This report makes no claim about customer impact beyond the signals it lists.",
            "",
            "_Machine-readable copies for tooling live beside this file: `packets.json`, "
            "`summary.csv`, and `manifest.json`._",
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
    corpus_has_closed: bool = True,
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
        "corpusHasClosed": corpus_has_closed,
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
