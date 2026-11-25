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
    "existing_fix": "Existing fix verified",
    "ready_to_close": "Ready for closure review",
}


def _save(path, lines):
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as f:
        f.write("\n".join(lines).rstrip() + "\n")
    os.replace(f.name, path)


def refresh_review(output_dir: Path):
    """Refresh both indexes after triage, fix events or follow-through completion."""
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
    for dest, prefix in ((root / "START-HERE.md", ""), (root / "02-fixes/INTAKE.md", "../")):

        def link(label, path):
            return f"[{label}]({prefix}{path})"

        lines = [
            "# Bug review",
            "",
            f"RHDH {audit['currentRelease']} · {len(cases)} bugs reviewed · {total} local PR proposals",
            "",
        ]
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
                if stage == "existing_fix" and packet.get("action") == "comment_only":
                    state += ", closure held"
                if not state:
                    state = "Local patch ready" if proposals else "Awaiting follow-through"
                first_line = (packet.get("proposedComment") or "").splitlines()
                finding = current.get("finding") or (
                    first_line[0] if first_line else packet.get("verdict", "").replace("_", " ")
                )
                lines.extend(
                    [
                        f"### {key} · {' '.join(packet['summary'].split())}",
                        "",
                        f"**{state}.** {finding}".rstrip(),
                    ]
                )
                if current.get("verification"):
                    lines.extend(["", f"**Checks.** {current['verification']}"])
                if current.get("blocker"):
                    lines.extend(["", f"**Blocked on.** {current['blocker']}"])
                if current.get("next"):
                    lines.extend(["", f"**Next step.** {current['next']}"])
                for proposal in proposals:
                    metadata = proposal.parent / "proposal.json"
                    info = json.loads(metadata.read_bytes()) if metadata.is_file() else {}
                    label = f"{info.get('repository', 'Proposal')} {info.get('branch', '')}".strip()
                    location = proposal.parent.relative_to(root)
                    refs = [
                        link(label, location / "PROPOSAL.md"),
                        link("patch", location / "change.patch"),
                        link("checks", location / "VERIFY.md"),
                    ]
                    targets = {
                        str(i): b["branch"]
                        for i, b in enumerate(info.get("backports", []), start=1)
                    }
                    for backport in sorted((proposal.parent / "backports").glob("*/change.patch")):
                        branch = targets.get(backport.parent.name, backport.parent.name)
                        refs.append(link(f"backport {branch}", backport.relative_to(root)))
                    lines.extend(["", "- " + " · ".join(refs)])
                actions = [link("Triage evidence", f"01-triage/audit/bugs/{key}.md")]
                delivery = current.get("delivery") or packet.get("commentPlan", {}).get(
                    "status", ""
                )
                if current.get("proposedComment", packet.get("proposedComment")):
                    actions.append(
                        link(
                            f"Jira draft ({delivery.replace('_', ' ')})",
                            f"01-triage/comments/{key}.md",
                        )
                    )
                if stage == "existing_fix":
                    fix = packet.get("fix") or {}
                    if fix.get("pr"):
                        actions.append(f"[Merged PR]({fix['pr']})")
                if plan:
                    actions.append(link("Plan", plan.relative_to(root)))
                evidence = current.get("evidence")
                if evidence:
                    for i, item in enumerate(
                        evidence if isinstance(evidence, list) else [evidence]
                    ):
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
        _save(dest, lines)
