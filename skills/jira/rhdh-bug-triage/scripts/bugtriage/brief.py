"""Self-contained per-ticket briefs for fresh-context investigator agents.

One ticket's material - facts, report, discussion, collected leads - rendered
as a single markdown file. An investigator subagent reads exactly one brief
instead of a multi-megabyte export, which keeps its context small and its
judgement independent of the other tickets in the sample.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .model import Ticket, load_export
from .report import write_text
from .run import RunError, load_sample_manifest

INVESTIGATOR_BRIEF = """\
## Your task (investigator)

You own this one bug, read-only, end to end. Write what you find in
`assessments/{key}.json`:

1. **What actually goes wrong** — trace how the reported steps reach the
   failure in the release's own source code. Do not just restate the report.
2. **What you checked** — every promise the bug makes (each acceptance
   requirement), marked passed, failed or unknown, each with a link that
   proves it.
3. **How it relates to other bugs** — compare it against the candidates
   listed below (and any better one you find), citing both tickets.
4. **Does it still happen in the release under review?** — answer with code,
   docs, dependency or runtime evidence tied to that exact release.
5. **A fix plan** — what a fix would change, where it would land (repository
   and file paths), and how big it is (trivial/small/moderate/large). If the
   verdict is duplicate, already fixed or no longer valid, describe the
   resolution action instead and use complexity `none`.

When asking someone to reproduce an issue, supply `reproductionSteps` in the finish result. Use ordered instructions: name the reported version and setup, the trigger, the expected result and the reported symptom. Then ask for the same test on the exact current release verified for the run, under equivalent starting conditions. State what to record for each version. If the original version or steps are missing, ask the reporter for them instead of guessing.

Never provision a cluster for triage. Trace the reported path in the released code, configuration and tests first. Link a verified shipped fix in the Jira draft. If the evidence identifies an outstanding defect, prepare and test a local PR proposal and link it in the draft. When the code and available evidence cannot distinguish the cause and an existing cluster is needed, keep the bug open. Set `clusterVerification` in the blocked finish result to the precise check a human can perform on their existing environment. This previews adding `rhdh-bug-needs-cluster` and asks the verifier to record the result and remove the label.

Read the description and comments for customer names. If one appears, set
`customerNamePresent: true` in the finish result and anonymize public-facing prose.
If the report and available evidence cannot establish how to reproduce the failure,
set `reporterReproRequest` to a short question asking for the specific missing
steps or sanitized observations. Never fill gaps with assumed reporter actions.

**Try to settle every unknown before writing it down.** If a check or the
verdict is heading for "unknown" or "unclear", first try the specific missing
check read-only: nightly test results on the public web, deeper digging into
vendored or built code, package registries, release records. Only write
"unknown" when that evidence genuinely does not exist — and say what you
tried. Never invent a result, and never claim you ran something you didn't."""


def _facts(ticket: Ticket) -> List[str]:
    def joined(values: List[str]) -> str:
        return ", ".join(values) if values else "(none)"

    lines = [
        "| Field | Value |",
        "|---|---|",
        f"| Status | {ticket.status or 'unknown'} |",
        f"| Created | {ticket.created or 'unknown'} |",
        f"| Team | {ticket.team or 'not established'} |",
        f"| Assignee | {ticket.assignee or 'unassigned'} |",
        f"| Affects versions | {joined(ticket.affects_versions)} |",
        f"| Fix versions | {joined(ticket.fix_versions)} |",
        f"| Labels | {joined(ticket.labels)} |",
    ]
    if ticket.links:
        for link in ticket.links:
            direction = "outward" if link.direction == "outward" else "inward"
            lines.append(f"| Link | {link.type} ({direction}) → {link.key} |")
    return lines


def render_brief(
    ticket: Ticket, evidence: Optional[Dict[str, Any]], sample_entry: Dict[str, Any]
) -> str:
    lines: List[str] = [
        f"# {ticket.key} — {ticket.summary}",
        "",
        f"Sample kind: {sample_entry.get('kind', 'aged')}"
        + (f" ({sample_entry.get('controlLabel')})" if sample_entry.get("controlLabel") else "")
        + f"; stratum: {sample_entry.get('stratum', '') or 'n/a'}.",
        "",
        "## Ticket facts",
        "",
        *_facts(ticket),
        "",
        "## Report",
        "",
        ticket.description.strip() or "(description empty or absent from the export)",
        "",
    ]
    if ticket.comments:
        lines += ["## Discussion", ""]
        for comment in ticket.comments:
            author = comment.author or "unknown author"
            lines += [f"**{author}** ({comment.created or 'undated'}):", "", comment.body, ""]
    else:
        lines += ["## Discussion", "", "(no comments)", ""]
    if evidence:
        discovery = evidence.get("discovery", {})
        leads = discovery.get("leads", [])
        lines += ["## Collected leads (not verdicts)", ""]
        for lead in leads:
            reasons = "; ".join(lead.get("foundBy", []))
            warnings = "; ".join(lead.get("warnings", [])) if lead.get("warnings") else ""
            lines.append(f"- {lead.get('key')}: {reasons}" + (f" — {warnings}" if warnings else ""))
        pulls = [pull.get("url") for pull in evidence.get("pullRequests", []) if pull.get("url")]
        if pulls:
            lines += ["", "**Pull requests found:**", ""]
            lines += [f"- {url}" for url in pulls]
        unsearched = evidence.get("unsearchedLinkedKeys", [])
        mode = evidence.get("searchMode", "unknown")
        lines += [
            "",
            f"Forge search mode: {mode}; unsearched linked keys: "
            + (", ".join(unsearched) if unsearched else "(none)")
            + ". Failed and unrun searches are not zero matches.",
            "",
        ]
    lines += [INVESTIGATOR_BRIEF.replace("{key}", ticket.key), ""]
    return "\n".join(lines)


def write_briefs(
    input_path: str,
    sample_path: str,
    output_dir: str,
    evidence_dir: str = "",
) -> Dict[str, str]:
    """Write one brief per sampled ticket; return the written paths."""
    tickets = {ticket.key: ticket for ticket in load_export(input_path)}
    sample = load_sample_manifest(sample_path)
    if evidence_dir:
        root = Path(evidence_dir)
        if not root.is_dir():
            raise RunError(f"evidence directory does not exist: {evidence_dir!r}")
    output = Path(output_dir)
    if output.exists():
        raise RunError("brief directory already exists; use a fresh directory")
    output.mkdir(parents=True, exist_ok=False)
    written: Dict[str, str] = {}
    for entry in sample.get("tickets", []):
        key = entry["key"]
        ticket = tickets.get(key)
        if ticket is None:
            raise RunError(f"sample names {key}, which is absent from the export")
        record: Optional[Dict[str, Any]] = None
        if evidence_dir:
            path = root / f"{key}.json"
            if path.is_file():
                record = json.loads(path.read_text(encoding="utf-8"))
        path = output / f"{key}.md"
        write_text(path, render_brief(ticket, record, entry))
        written[key] = str(path)
    return written
