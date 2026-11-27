"""Build current reviewer views from the triage packet, follow-through and local receipts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

STAGES = {
    "patch": "Local patch ready",
    "blocked": "Blocked",
    "verified_resolution": "Resolution verified",
    "classification_review": "Issue type needs human review",
    "existing_fix": "Fix already shipped",
    "ready_to_close": "Ready for closure review",
}


def _save(path, lines):
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as f:
        f.write("\n".join(lines).rstrip() + "\n")
    os.replace(f.name, path)


def batch_counts(reviewed, excluded):
    customers = sum(row.get("reason", "").startswith("customer-linked") for row in excluded)
    counts = f"{reviewed + len(excluded)} examined · {reviewed} reviewed · {len(excluded)} excluded"
    return f"{counts} ({customers} customer-linked)" if customers else counts


def refresh_review(output_dir: Path):
    """Refresh the review index after triage, fix events or follow-through completion."""
    root = Path(output_dir)
    packets_file = root / "01-triage/audit/packets.json"
    if not (root / "run.json").is_file() or not packets_file.is_file():
        return
    summary = json.loads((root / "run.json").read_bytes())
    audit = json.loads(packets_file.read_bytes())
    cases = []
    for packet in audit["packets"]:
        key = packet["key"]
        plans = sorted((root / "02-fixes").glob(f"*/{key}/PLAN.md"))
        plan = plans[0] if plans else None
        proposals = sorted((root / "02-fixes/events" / key).glob("*/PROPOSAL.md"))
        proposals = [p for p in proposals if (p.parent / "receipt.json").is_file()]
        is_pr = bool(proposals or (plan and plan.parent.parent.name in {"docs", "pull-requests"}))
        cases.append((packet, plan, proposals, is_pr))

    total = sum(len(row[2]) for row in cases)

    def link(label, path):
        return f"[{label}]({path})"

    lines = [
        "# Bug review",
        "",
        f"RHDH {audit['currentRelease']} · {len(cases)} bugs reviewed · {total} local PR proposals",
        "",
    ]
    selection = packets_file.with_name("selection.json")
    if audit.get("meta", {}).get("coverage", {}).get("inventoryHash") and selection.is_file():
        exclusions = json.loads(selection.read_bytes())["excluded"]
        lines[2] = (
            f"RHDH {audit['currentRelease']} · {batch_counts(len(cases), exclusions)} · {total} local PR proposals"
        )
    for title, pr_queue in (("PR queue", True), ("Other outcomes", False)):
        lines.extend([f"## {title}", ""])
        group = [row for row in cases if row[3] == pr_queue]
        if not group:
            lines.extend(["None in this batch.", ""])
        for packet, plan, proposals, _ in group:
            key = packet["key"]
            current = summary.get("cases", {}).get(key, {})
            stage = current.get("stage", "")
            state = STAGES.get(stage, stage.replace("_", " ").capitalize())
            metadata = {}
            for proposal in proposals:
                path = proposal.parent / "proposal.json"
                metadata[proposal] = json.loads(path.read_bytes()) if path.is_file() else {}
            if proposals and stage in {"", "patch"}:
                kinds = {item.get("kind") for item in metadata.values()}
                state = {
                    frozenset({"docs"}): "Documentation patch prepared locally",
                    frozenset({"code"}): "Code fix prepared locally",
                    frozenset({"code", "docs"}): "Code and documentation patches prepared locally",
                }.get(frozenset(kinds), "Local patch prepared")
            if stage == "existing_fix" and packet.get("action") == "comment_only":
                state += ", closure held"
            if not state:
                state = "Local patch ready" if proposals else "Awaiting follow-through"
            first_line = (packet.get("proposedComment") or "").splitlines()
            finding = (
                current.get("resolution")
                or current.get("finding")
                or (first_line[0] if first_line else packet.get("verdict", "").replace("_", " "))
            )
            lines.extend(
                [
                    f"### {key} · {' '.join(packet['summary'].split())}",
                    "",
                    f"**{state}.** {finding}".rstrip(),
                ]
            )
            for message in current.get("jiraFieldSummary", []):
                lines.extend(["", message])
            transition = current.get("jiraTransition", {})
            if transition:
                status = transition["observed"]
                if transition["state"] == "proposed_after_comment":
                    handoff = f"Observed **{status}**. Proposed move to **In Review** after the reviewed comment is posted and confirmed. Read-only preview."
                elif transition["state"] == "already_in_review":
                    handoff = f"Observed **{status}**. No transition needed."
                else:
                    handoff = f"Observed **{status}**. No transition proposed."
                lines.extend(["", f"**Jira handoff.** {handoff}"])
            if current.get("verification"):
                lines.extend(["", f"**Checks.** {current['verification']}"])
            if current.get("blocker"):
                lines.extend(["", f"**Blocked on.** {current['blocker']}"])
            lines.extend(["", "**Who does what next**", ""])
            linked = set()
            if current.get("fixedNextStep"):
                lines.append(current["fixedNextStep"])
            elif current.get("nextActions"):
                for assignment in current["nextActions"]:
                    refs = []
                    for item in assignment.get("links", []):
                        refs.append(link(item["label"], item["path"]))
                        linked.add(item["path"])
                    lines.append(
                        " ".join(
                            [
                                f"- **{assignment['owner']}** — {assignment['action']}",
                                " · ".join(refs),
                            ]
                        ).rstrip()
                    )
            elif current.get("next"):
                lines.append(f"Owner unrecorded — {current['next']}")
            else:
                lines.append(
                    "Triage investigator — complete the investigation and record the handoff."
                )
            for proposal in proposals:
                info = metadata[proposal]
                label = f"{info.get('repository', 'Proposal')} {info.get('branch', '')}".strip()
                location = proposal.parent.relative_to(root)
                refs = [
                    (label, location / "PROPOSAL.md"),
                    ("patch", location / "change.patch"),
                    ("checks", location / "VERIFY.md"),
                ]
                targets = {
                    str(i): b["branch"] for i, b in enumerate(info.get("backports", []), start=1)
                }
                for backport in sorted((proposal.parent / "backports").glob("*/change.patch")):
                    branch = targets.get(backport.parent.name, backport.parent.name)
                    refs.append((f"backport {branch}", backport.relative_to(root)))
                remaining = [link(label, path) for label, path in refs if str(path) not in linked]
                if remaining:
                    lines.extend(["", "- " + " · ".join(remaining)])
            actions = [link("Triage evidence", f"01-triage/audit/bugs/{key}.md")]
            delivery = current.get("delivery") or packet.get("commentPlan", {}).get("status", "")
            if current.get("proposedComment", packet.get("proposedComment")):
                actions.append(
                    link(
                        f"Jira draft ({delivery.replace('_', ' ')})",
                        f"01-triage/comments/{key}.md",
                    )
                )
            if stage == "existing_fix" and not current.get("fixedNextStep"):
                fix = packet.get("fix") or {}
                if fix.get("pr"):
                    actions.append(f"[Merged PR]({fix['pr']})")
            if plan:
                actions.append(link("Plan", plan.relative_to(root)))
            evidence = current.get("evidence")
            if evidence:
                for i, item in enumerate(evidence if isinstance(evidence, list) else [evidence]):
                    actions.append(
                        link("Verification evidence" if i == 0 else f"Evidence {i + 1}", item)
                    )
            lines.extend(["", " · ".join(actions), ""])
    lines.extend(
        [
            link("Triage snapshot", "01-triage/START-HERE.md")
            + " · "
            + link("Folder guide", "02-fixes/README.md")
        ]
    )
    _save(root / "START-HERE.md", lines)
    # Older runs linked the same queue from both phases. Migrate their generated navigation.
    legacy = root / "02-fixes/INTAKE.md"
    if legacy.is_file() and legacy.read_text().startswith("# Bug review\n"):
        references = [
            (
                root / "01-triage/START-HERE.md",
                "`../02-fixes/INTAKE.md`",
                "[Review index](../START-HERE.md)",
            ),
            (root / "02-fixes/README.md", "(INTAKE.md)", "(../START-HERE.md)"),
            (root / "02-fixes/AUDIT.md", "(INTAKE.md)", "(../START-HERE.md)"),
        ]
        for path in (root / "02-fixes").glob("*/*/CASE.md"):
            references.append((path, "(../../INTAKE.md)", "(../../../START-HERE.md)"))
        for path, old, new in references:
            if path.is_file():
                original = path.read_text()
                if old in original:
                    _save(path, original.replace(old, new).splitlines())
        legacy.unlink()
