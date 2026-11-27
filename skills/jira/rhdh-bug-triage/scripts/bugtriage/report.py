"""Shared rendering helpers and the optional full dossier.

The phased layout in :mod:`layout` is the primary human view. This module keeps
the manifest builder and the file writers, plus a compatibility renderer for
callers that still want the older single-document view.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .model import Ticket
from .policy import CLOSE_ACTIONS, Packet, investigation_outcome

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
    plain_status = {
        "propose": "ready for a human to review and post",
        "review_required": "on hold until someone checks the ticket's past comments",
        "suppress": "not repeated — the same advice was already given earlier",
    }.get(plan["status"], plan["status"])
    return [f"**Posting this comment:** {plain_status} — {plan['reason']}", ""]


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
    backlog_size: int,
    excluded: List[Dict[str, str]],
    selection: Dict[str, Dict[str, Any]],
    thresholds: Dict[str, float],
    backlog_has_closed: bool = True,
    coverage: Optional[Dict[str, Any]] = None,
    release_evidence: str = "",
) -> str:
    coverage = coverage or {}
    drafts = sum(surfaced(p) for p in packets)
    delivery = {
        status: sum(p.comment_plan.get("status") == status for p in packets)
        for status in ("propose", "review_required", "suppress")
    }
    investigations = {
        status: sum(p.investigation.get("status", "not_recorded") == status for p in packets)
        for status in ("completed", "blocked", "not_recorded")
    }
    outcomes = {
        outcome: sum(investigation_outcome(p) == outcome for p in packets)
        for outcome in (
            "requirements_satisfied_in_stated_scope",
            "requirement_violated",
            "not_determined",
            "not_recorded",
            "invalid",
        )
    }
    lines = [
        f"# RHDH bug triage — {as_of.date().isoformat()}",
        "",
        DRY_RUN_BANNER,
        "",
        "Every bug we reviewed appears below, including the ones where a check could not be finished. "
        "A draft comment is not permission to post it. Suppressed drafts (advice already given earlier) "
        "are shown for inspection only and must not be sent again.",
        "",
        f"**Bottom line:** {len(packets)} bugs reviewed; {drafts} comment drafts; "
        f"{sum(p.action in CLOSE_ACTIONS for p in packets)} recommendation(s) to close a bug.",
        "",
        f"- Comments ready for a human to review and post (`propose`): {delivery['propose']}. On hold until the ticket's past comments are checked (`review_required`): {delivery['review_required']}. Already suggested before, so not repeated (`suppress`): {delivery['suppress']}.",
        f"- Fix plans written: {sum(bool(p.fix_plan.get('approach')) for p in packets)} of {len(packets)}. A plan says where a fix would go — it is not a change and not permission to close the bug.",
        f"- Comparisons with other bugs that the evidence supports: {sum(c.get('relationship') == 'duplicate_supported' for p in packets for c in p.comparisons)}. Fixes fully verified in their stated scope: {sum(p.fix_evidence.get('state') == 'verified_for_stated_scope' for p in packets)}. Partial fixes: {sum(p.fix_evidence.get('state') == 'partial_fix_supported' for p in packets)}. None of these are closures.",
        f"- Investigations finished: {investigations['completed']}; stopped at a missing check: {investigations['blocked']}. A stopped check is not a finished one.",
        f"- What the checks found: passed {outcomes['requirements_satisfied_in_stated_scope']}, failed {outcomes['requirement_violated']}, not settled {outcomes['not_determined']}. This only covers the scope each investigator looked at.",
        f"- Reviewed: {len(packets)} bugs ({control_count} of them control bugs with known answers). Scope: {'bugs at least 90 days old' if coverage.get('scope', 'aged') == 'aged' else 'all open bugs'}.",
        f"- Bugs searched for duplicates and fixes: {backlog_size}. Release under review: {current_release}.",
        f"- Proof of that release: {release_evidence or 'not supplied'}.",
        f"- Picked {coverage.get('selectedIssues', len(packets))} of {coverage.get('eligibleIssues', 'unknown')} eligible bugs; {len(excluded)} were excluded, with reasons in audit/selection.json.",
        "- We only searched the bugs listed above; that list is not the whole tracker, and 'no match found' never proves a bug is unique.",
        "",
        "## The exact comments we would post",
        "",
    ]
    if not packets:
        lines += [
            "No bugs matched the rules for this run. Nothing was silently marked as triaged.",
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
            lines += [
                "No comment draft: this issue was already closed or the inputs were insufficient."
            ]
        lines += [
            "",
            "**Not posted:** this is a preview. Even after approval, the only action is posting the comment — "
            "closing, fixing, PRs and backports are separate, explicitly approved work.",
            "",
        ]
        if packet.notes:
            lines += [f"**Notes for the reviewer:** {packet.notes}", ""]
        if packet.fix_plan:
            plan = packet.fix_plan
            lines += [
                "**Fix plan (guidance only — not a change, not permission to close):** "
                + str(plan.get("approach", "not stated")),
                "",
            ]
            for area in plan.get("areas", []) or []:
                if isinstance(area, dict):
                    paths = ", ".join(area.get("paths", []) or [])
                    lines += [f"- Where: {area.get('repository', 'unknown')} — {paths}"]
            lines += [f"- Size of the fix: {plan.get('complexity', 'unknown')}", ""]
        if packet.verification:
            v = packet.verification
            lines += [
                "**Source snapshots taken (hashed copies of what we read):** "
                "a human still has to read them before accepting anything.",
                "",
            ]
            for repository in v["repositories"]:
                lines.append(
                    f"- Source: {repository['repository']} @ `{repository['revision'] or 'unresolved'}` (asked for `{repository['requestedRef']}`)."
                )
                for pull in repository["pullRequests"]:
                    lines.append(
                        f"  - {pull['ref']}: `{pull['containment']}`; the actual diff {'was read' if pull.get('diff') is not None else 'was not available'}."
                    )
            for artifact in v["artifacts"]:
                lines.append(
                    f"- Released image: {artifact['releaseReference']}; ties back to the source: `{artifact['sourceBinding']}`; {len(artifact['objects'])} checksum-checked metadata objects read."
                )
            lines += ["", "**Gaps in what we could fetch:** " + "; ".join(v["gaps"]), ""]
        for comparison in packet.comparisons:
            lines += [
                f"**Compared with {comparison.get('key')}** (`{comparison.get('relationship')}`) — {comparison.get('summary')} "
                "This comparison is our judgement, not permission to close anything.",
                "",
            ]
        if packet.fix_evidence:
            lines += [
                f"**How much of the fix is proven:** `{packet.fix_evidence.get('state', 'not_assessed')}` (separate from whether the bug may be closed).",
                "",
                f"**The scope that was checked:** {packet.fix_evidence.get('scenario', 'not established')}",
                "",
                "**Not yet verified:** " + "; ".join(packet.fix_evidence.get("unverified", [])),
                "",
            ]
            for claim in packet.fix_evidence.get("covered", []):
                if isinstance(claim, dict):
                    lines += [
                        f"- What is covered: {claim.get('summary', '')}; sources: {claim.get('refs', [])}"
                    ]
            lines.append("")
        discovery = packet.discovery
        if discovery:
            lines += ["**Leads found while searching (leads, not verdicts):**", ""]
            for lead in discovery.get("leads", []):
                lines.append(
                    f"- {lead['key']}: found by {', '.join(lead['foundBy'])}"
                    + ("; " + "; ".join(lead["warnings"]) if lead.get("warnings") else "")
                )
            queries = discovery.get("collection", discovery).get("queries", [])
            outcomes = {
                name: sum(q.get("outcome") == name for q in queries)
                for name in ("returned", "empty", "capped", "failed", "not_run")
            }
            lines += [
                "",
                f"**Jira searches:** {outcomes}. A failed, cut-short or never-run search is not the same as 'nothing found'.",
                "",
            ]
        if packet.gaps:
            lines += ["**Limits:** " + "; ".join(packet.gaps), ""]
        collected = coverage.get("collection", {}).get(packet.key, {})
        if collected:
            searches = collected.get("searches", [])
            failures = sum(s.get("status") != "success" for s in searches)
            lines += [
                f"**GitHub searches:** {collected.get('searchMode', 'unknown')}; {len(searches)} queries, {failures} failed or invalid. A failed search is not 'nothing found'.",
                "",
            ]
        lines += ["---", ""]
    lines += [
        "## How this run worked, and what it cannot promise",
        "",
        f"- Bugs were picked with this query: `{jql}`.",
        f"- A bug is only recommended for closing when the evidence score is at least {thresholds['duplicate']:.2f} for duplicates "
        f"or {thresholds['fixed']:.2f} for already-fixed bugs — and even then only with cited proof for each claim and two "
        "independent reviews that agree. Looking similar or scoring high is never enough.",
        "- When two bugs look like duplicates, the older report is the one to keep. We check real creation dates, "
        "not issue numbers. If the candidate is newer or undated, a human picks; we do not propose it.",
        "- Calling a bug 'already fixed' means: the fix covers the whole reported problem, it is merged, and there is "
        "direct proof it shipped in the release under review (or an earlier one). A partial fix, or one that has not "
        "shipped yet, is never a close recommendation.",
        "- The evidence score measures how strong the citations are. It is not a probability and not a guarantee. "
        "Reviewers must open the cited links; reading code is not the same as running it.",
        "- A bug being open, or our search finding no fix, does not prove the bug still exists. 'Still valid' and "
        "'no longer valid' both need evidence tied to the exact release under review.",
        "- Customer-linked and already-closed bugs never get automated comments.",
        "- 'Suppressed' means we stay silent because the same advice was already given. It does not mean anyone gets notified.",
        "- Missing data and disagreement are written down as uncertainty, never hidden. We do not send generic "
        "'please reproduce' pings or reminders.",
        "- The assessments are agent judgements over cited snapshots. Structure checks and independent reviewers "
        "reduce mistakes; they do not guarantee correctness.",
        f"- Generated {generated_at}; nothing was written to Jira.",
    ]
    lines.append(
        "- The search for duplicates covered both open and closed bugs."
        if backlog_has_closed
        else "- **The bug list we searched had no closed bugs**, so a closed original would have been invisible. "
        "Search a list that includes closed bugs; finding no match does not prove this bug is unique."
    )
    if excluded:
        lines += [
            f"- {len(excluded)} bug(s) were excluded from selection; the reasons are in packets.json."
        ]
    return "\n".join(lines) + "\n"


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
    backlog_size: int,
    backlog_has_closed: bool = True,
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
        "backlogSize": backlog_size,
        "backlogHasClosed": backlog_has_closed,
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
