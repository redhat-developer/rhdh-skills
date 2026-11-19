"""Self-contained per-ticket dossiers for fresh-context investigator agents.

One ticket's material - facts, report, discussion, collected leads - rendered
as a single markdown file. An investigator subagent reads exactly one dossier
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

You are investigating this one bug read-only, end to end. Produce, in
`assessments/{key}.json`:

1. **Mechanism and root cause** - how the reported inputs reach the failure,
   traced in the actual release sources, not just restated from the report.
2. **Requirement checks** - every acceptance requirement observed as
   satisfied, violated or unknown, with direct method-matching citations.
3. **Relations** - comparisons against the duplicate/related candidates
   below (and any better candidate you find), with citations of both reports.
4. **Validation on the exact release** - code, runtime, documentation or
   dependency evidence bound to the release under review.
5. **A fix plan** - the concrete read-only remediation approach: where a fix
   would land (repository and paths), what it would change, and a complexity
   estimate. For duplicate/already-fixed/obsolete verdicts, describe the
   resolution action instead and use complexity `none`.

**Escalate before recording an unknown.** If a requirement or the disposition
would land on unknown/unclear, first attempt the specific missing check
through read-only means - CI/nightly job results on the web, deeper source
tracing including vendored or built code, package-registry metadata, release
records. Only record unknown when the read-only evidence genuinely does not
exist, and name exactly what was attempted. Never fabricate a result, and
never claim a runtime check that was not performed."""


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


def render_dossier(
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


def write_dossiers(
    input_path: str,
    sample_path: str,
    output_dir: str,
    evidence_dir: str = "",
) -> Dict[str, str]:
    """Write one dossier per sampled ticket; return the written paths."""
    tickets = {ticket.key: ticket for ticket in load_export(input_path)}
    sample = load_sample_manifest(sample_path)
    if evidence_dir:
        root = Path(evidence_dir)
        if not root.is_dir():
            raise RunError(f"evidence directory does not exist: {evidence_dir!r}")
    output = Path(output_dir)
    if output.exists():
        raise RunError("dossier directory already exists; use a fresh directory")
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
        write_text(path, render_dossier(ticket, record, entry))
        written[key] = str(path)
    return written
