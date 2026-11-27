"""Phased output layout for a dry-run triage.

One run produces two phases under the output root:

- ``01-triage/``: the decision page, exact comment drafts, and the proof.
- ``02-fixes/``: a handoff scaffold for the separately approved write phase.

The module only writes local files. It never comments, closes, branches, or
opens a pull request.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

from .model import Ticket
from .policy import Packet
from .report import write_json, write_text
from .review_queue import refresh_review

TRIAGE = "01-triage"
FIXES = "02-fixes"

OUTCOMES = ("pull-requests", "docs", "new-bugs", "resolution", "blocked")
OUTCOME_LABELS = {
    "pull-requests": "pull request",
    "docs": "documentation change",
    "new-bugs": "new Jira issue",
    "resolution": "resolution only",
    "blocked": "blocked on a check",
}
DOCS_REPOSITORY = "red-hat-developers-documentation-rhdh"


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _one_line(value: Any, limit: int = 180) -> str:
    text = " ".join(_text(value).split())
    if not text:
        return ""
    for stop in (". ", "? ", "! "):
        if stop in text:
            text = text.split(stop, 1)[0] + stop.strip()
            break
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _cell(value: Any) -> str:
    return _one_line(value).replace("|", "\\|")


def _ref_link(ref: str) -> str:
    ref = _text(ref).strip()
    if not ref:
        return ""
    if ref.startswith(("https://", "http://")):
        return f"[{ref}]({ref})"
    if "-" in ref and ref.split("-", 1)[0].isupper():
        return f"[{ref}](https://redhat.atlassian.net/browse/{ref})"
    return ref


def _refs(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    return "; ".join(link for link in (_ref_link(value) for value in values) if link)


def _owner(ticket: Ticket) -> str:
    team = ticket.team or "team not established"
    return f"{team}; {ticket.assignee or 'unassigned'}"


def _post_status(packet: Packet) -> str:
    plan = packet.comment_plan or {}
    return _text(plan.get("status"), "not drafted")


def _post_reason(packet: Packet) -> str:
    plan = packet.comment_plan or {}
    return _text(plan.get("reason"), "no comment plan")


def _reason(packet: Packet) -> str:
    validation = packet.validation or {}
    if packet.verdict == "no_longer_valid":
        proof = (packet.proof or {}).get("scopeRemoval") or {}
        return _one_line(proof.get("summary") or validation.get("summary"))
    if packet.verdict == "unclear":
        investigation = packet.investigation or {}
        return _one_line(investigation.get("blocker") or validation.get("summary"))
    return _one_line(validation.get("summary") or packet.notes)


def _normalise_outcome(value: Any) -> str:
    raw = _text(value).strip().lower().replace("_", "-")
    aliases = {
        "pull-request": "pull-requests",
        "pull-requests": "pull-requests",
        "pr": "pull-requests",
        "doc": "docs",
        "docs": "docs",
        "new-bug": "new-bugs",
        "new-bugs": "new-bugs",
        "issue": "new-bugs",
        "resolution": "resolution",
        "blocked": "blocked",
    }
    return aliases.get(raw, "")


def fix_outcome(packet: Packet) -> str:
    """Route one finding to the phase that can act on it.

    An explicit ``handoff.outcome`` wins. Otherwise the verdict and fix plan
    decide: unresolved checks block, resolution-only verdicts do not open code,
    and documentation repositories stay with the docs team.
    """
    explicit = _normalise_outcome((packet.handoff or {}).get("outcome"))
    if explicit:
        return explicit
    if packet.verdict in ("duplicate", "already_fixed", "no_longer_valid"):
        return "resolution"
    if packet.verdict == "unclear" or (packet.investigation or {}).get("status") == "blocked":
        return "blocked"
    plan = packet.fix_plan or {}
    if _text(plan.get("complexity")).strip().lower() == "none":
        return "resolution"
    areas = [area for area in (plan.get("areas") or []) if isinstance(area, dict)]
    repositories = [_text(area.get("repository")).strip() for area in areas]
    if repositories and all(DOCS_REPOSITORY in repository for repository in repositories):
        return "docs"
    return "pull-requests"


def _outcome_counts(packets: List[Packet]) -> Dict[str, int]:
    counts = {outcome: 0 for outcome in OUTCOMES}
    for packet in packets:
        counts[fix_outcome(packet)] += 1
    return counts


def _delivery_counts(packets: List[Packet]) -> Dict[str, int]:
    return {
        status: sum(_post_status(packet) == status for packet in packets)
        for status in ("propose", "review_required", "suppress")
    }


def _verdict_counts(packets: List[Packet]) -> Dict[str, int]:
    from collections import Counter

    return dict(sorted(Counter(packet.verdict for packet in packets).items()))


def _investigation_counts(packets: List[Packet]) -> Dict[str, int]:
    return {
        status: sum(
            (p.investigation or {}).get("status", "not_recorded") == status for p in packets
        )
        for status in ("completed", "blocked", "not_recorded")
    }


def _case_status(packet: Packet) -> str:
    if fix_outcome(packet) == "resolution" and packet.verdict == "unclear":
        return "resolution held"
    if fix_outcome(packet) == "blocked":
        return "blocked"
    if _post_status(packet) == "suppress":
        return "comment suppressed; follow-through remains open"
    return "awaiting local follow-through"


def _case_action(packet: Packet) -> str:
    outcome = fix_outcome(packet)
    if outcome == "resolution" and packet.verdict == "unclear":
        return "Resolve the recorded review hold before considering closure."
    if outcome == "resolution":
        return "Review the resolution: close, retarget, or verify the finding. No code change is proposed."
    if outcome == "blocked":
        blocker = (packet.investigation or {}).get("blocker") or ""
        if not blocker.strip():
            return "Do the one missing check named in the investigation record, then re-triage."
        return f"Do the missing check first: {_one_line(blocker, 240)}"
    if outcome == "docs":
        return (
            "Update the documentation named in the fix plan, then verify the "
            f"{packet.current_release} page."
        )
    if outcome == "new-bugs":
        return "Draft the follow-up Jira issue and record what it would unblock."
    return "Prepare the local patch, run the named tests, and record a PR proposal."


def _fix_areas(plan: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for area in plan.get("areas") or []:
        if not isinstance(area, dict):
            continue
        repository = _text(area.get("repository"), "repository not stated")
        paths = ", ".join(_text(path) for path in (area.get("paths") or []))
        lines.append(f"- `{repository}` — {paths or 'paths not stated'}")
    return lines


def _requirements(packet: Packet) -> List[str]:
    requirements = (packet.investigation or {}).get("requirements") or []
    if not requirements:
        return ["_No requirement-level checks recorded._"]
    lines = ["| Requirement | Result | Method | Evidence |", "|---|---|---|---|"]
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        lines.append(
            "| "
            + _cell(requirement.get("statement"))
            + " | "
            + _cell(requirement.get("result"))
            + " | "
            + _cell(requirement.get("method"))
            + " | "
            + _refs(requirement.get("refs"))
            + " |"
        )
    return lines


def _proof(packet: Packet) -> List[str]:
    proof = packet.proof or {}
    if not proof:
        return ["_No named proof claims recorded._"]
    lines: List[str] = []
    for claim, value in proof.items():
        if not isinstance(value, dict):
            continue
        lines += [
            f"### {claim}",
            "",
            _text(value.get("summary"), "No summary recorded."),
            "",
        ]
        refs = _refs(value.get("refs"))
        if refs:
            lines += [f"Sources: {refs}", ""]
    return lines


def _evidence(packet: Packet) -> List[str]:
    if not packet.evidence:
        return ["_No evidence recorded._"]
    lines: List[str] = []
    for item in packet.evidence:
        lines.append(
            f"- **{item.type}** ({item.strength}): {_text(item.why)} — {_ref_link(item.ref)}"
        )
    return lines


def _comparisons(packet: Packet) -> List[str]:
    if not packet.comparisons:
        return ["_No comparisons recorded._"]
    lines: List[str] = []
    for comparison in packet.comparisons:
        if not isinstance(comparison, dict):
            continue
        lines.append(
            f"- **{_text(comparison.get('key'))}** (`{_text(comparison.get('relationship'))}`): "
            + _text(comparison.get("summary"))
        )
        refs = _refs(comparison.get("refs"))
        if refs:
            lines.append(f"  Sources: {refs}")
    return lines


def render_start_here(
    packets: List[Packet],
    tickets: Dict[str, Ticket],
    *,
    as_of: str,
    current_release: str,
    release_evidence: str,
    excluded_count: int,
    corpus_size: int = 0,
) -> str:
    verdicts = _verdict_counts(packets)
    delivery = _delivery_counts(packets)
    outcomes = _outcome_counts(packets)
    investigations = _investigation_counts(packets)
    customer_complete = sum(1 for packet in packets if tickets[packet.key].customer_fields_complete)
    lines = [
        f"# RHDH bug triage — {as_of}",
        "",
        "**Dry run.** Nothing was posted, transitioned, linked, or written to Jira. "
        "No bugs were closed and no PRs were created. The comments in `comments/` are previews.",
        "",
        "## Result",
        "",
        "| Metric | Count |",
        "|---|---|",
        f"| Bugs reviewed | {len(packets)} |",
        f"| Still valid on {current_release} | {verdicts.get('still_valid', 0)} |",
        f"| No longer valid on {current_release} | {verdicts.get('no_longer_valid', 0)} |",
        f"| Needs reproduction | {verdicts.get('needs_repro', 0)} |",
        f"| Unclear | {verdicts.get('unclear', 0)} |",
        f"| Duplicate | {verdicts.get('duplicate', 0)} |",
        f"| Already fixed | {verdicts.get('already_fixed', 0)} |",
        f"| Comments ready to propose | {delivery.get('propose', 0)} |",
        f"| Comments on hold for review | {delivery.get('review_required', 0)} |",
        f"| Comments suppressed | {delivery.get('suppress', 0)} |",
        f"| Fix cases: pull request (code and documentation) | {outcomes['pull-requests'] + outcomes['docs']} |",
        f"| Fix cases: new Jira issue | {outcomes['new-bugs']} |",
        f"| Fix cases: resolution only | {outcomes['resolution']} |",
        f"| Fix cases: blocked | {outcomes['blocked']} |",
        f"| Investigations completed | {investigations['completed']} |",
        f"| Investigations blocked | {investigations['blocked']} |",
        f"| Customer-field coverage complete | {customer_complete} of {len(packets)} |",
        f"| Bugs excluded from selection | {excluded_count} |",
        "",
        "## Decisions",
        "",
        "| Bug | Verdict | Comment | Fix phase | Owner | One-line reason |",
        "|---|---|---|---|---|---|",
    ]
    for packet in packets:
        ticket = tickets[packet.key]
        lines.append(
            "| "
            + f"[{packet.key}](audit/bugs/{packet.key}.md)"
            + " | "
            + _cell(packet.verdict)
            + " | "
            + _cell(
                _post_status(packet)
                + (
                    " — " + _post_reason(packet)
                    if _post_status(packet) == "review_required"
                    else ""
                )
            )
            + " | "
            + _cell(fix_outcome(packet))
            + " | "
            + _cell(_owner(ticket))
            + " | "
            + _cell(_reason(packet))
            + " |"
        )
    lines += [
        "",
        "## What is in this folder",
        "",
        "- `comments/` — one exact draft per bug. Nothing here has been posted.",
        "- `audit/` — proof, verification method, limits, selection, and the machine record.",
        f"- `../{FIXES}/` — local case plans, patch proposals and verification receipts.",
        "",
        "## Read in this order",
        "",
        "1. This page for the decision.",
        "2. `comments/KEY.md` for the draft you care about.",
        "3. `audit/bugs/KEY.md` for why it says that.",
        "4. `audit/RUN.md` for run-wide caveats.",
        "5. [Review index](../START-HERE.md) for the fix handoff.",
        "",
        "## How the run worked",
        "",
        f"1. Recorded the supplied release `{current_release}` and evidence link; the CLI does not verify the release record's contents.",
        f"2. Loaded the export and assessed {len(packets)} selected bugs; {excluded_count} were excluded with reasons. Scope and controls are recorded in `audit/selection.json`.",
        f"3. Searched a local comparison corpus of {corpus_size} bugs for duplicate and fix leads. Its open/closed coverage and collection limits are in `audit/RUN.md`.",
        f"4. Loaded investigator assessments: {investigations['completed']} completed, {investigations['blocked']} blocked, {investigations['not_recorded']} not recorded. The CLI does not establish whether investigators used independent contexts.",
        "5. Checked evidence shape, method matching and proof gates, then routed each finding to `02-fixes/`.",
        "",
        "## Limits",
        "",
        "- The release under review is recorded in `audit/release.md`; the CLI records the supplied evidence link and does not verify its contents.",
        f"- Customer-field coverage is complete for {customer_complete} of {len(packets)} assessed bugs. Delivery status also depends on history and proof checks; it is not permission to post.",
        "- Code reading is not running the product. Runtime claims are labelled as unproven or blocked.",
        "- A failed or cut-short search is not a zero result. See `audit/RUN.md`.",
        "",
        "The method and its limits are in `audit/METHOD.md`. The release record is in `audit/release.md`.",
        "",
        f"Release evidence: {release_evidence or 'not supplied'}",
        "",
    ]
    return "\n".join(lines)


def render_comment_file(packet: Packet) -> str:
    return packet.proposed_comment.rstrip() + "\n" if packet.proposed_comment else ""


def render_bug_audit(packet: Packet, ticket: Ticket) -> str:
    investigation = packet.investigation or {}
    validation = packet.validation or {}
    plan = packet.fix_plan or {}
    lines = [
        f"# {packet.key} — {packet.summary}",
        "",
        "## Disposition",
        "",
        f"- Verdict: `{packet.verdict}`",
        f"- Comment status: `{_post_status(packet)}` — {_post_reason(packet)}",
        f"- Fix phase: `{fix_outcome(packet)}` — {OUTCOME_LABELS[fix_outcome(packet)]}",
        f"- Owner: {_owner(ticket)}",
        f"- Next step: {_text(packet.recommended_step, 'Review the finding and decide.')}",
        "",
        "## What we verified",
        "",
        f"- Investigation: `{_text(investigation.get('status'), 'not recorded')}`",
        f"- Release: `{_text(validation.get('release'), packet.current_release or 'not recorded')}`",
        f"- Method: `{_text(validation.get('method'), 'not recorded')}`",
        f"- Result: `{_text(validation.get('result'), 'not recorded')}`",
        f"- Scope: {_text(investigation.get('scope'), 'not recorded')}",
        "",
        "## What goes wrong",
        "",
        _text(investigation.get("mechanism"), "No causal mechanism recorded."),
        "",
        "## Requirements checked",
        "",
        *_requirements(packet),
        "",
        "## Current-release validation",
        "",
        _text(validation.get("summary"), "No validation summary recorded."),
        "",
        f"Sources: {_refs(validation.get('refs'))}",
        "",
        "## Proof",
        "",
        *_proof(packet),
        "",
        "## Fix plan",
        "",
        f"- Approach: {_text(plan.get('approach'), 'No fix plan recorded.')}",
        f"- Size: `{_text(plan.get('complexity'), 'unknown')}`",
        *_fix_areas(plan),
        "",
        "## What to do with the bug",
        "",
        _case_action(packet),
        "",
        f"Recommended step from the assessment: {_text(packet.recommended_step, 'not stated')}",
        "",
        "## Limits and blockers",
        "",
    ]
    limits = list(packet.gaps or [])
    if investigation.get("blocker"):
        limits.append("Blocker: " + _text(investigation.get("blocker")))
    for error in packet.verification_errors or []:
        limits.append("Check failure: " + _text(error))
    if not limits:
        limits.append("None recorded.")
    lines += [f"- {limit}" for limit in limits]
    lines += [
        "",
        "## Comparisons",
        "",
        *_comparisons(packet),
        "",
        "## Evidence",
        "",
        *_evidence(packet),
        "",
    ]
    return "\n".join(lines)


def render_method(
    *,
    current_release: str,
    release_evidence: str,
    jql: str,
    thresholds: Dict[str, float],
) -> str:
    return "\n".join(
        [
            "# Method",
            "",
            "This is a read-only triage. The workflow is:",
            "",
            "1. **Verify the release.** The release under review is recorded in `release.md`; the tool records the supplied evidence link but does not verify its contents.",
            "2. **Read the bugs in full.** The export carries descriptions, comments, links, versions, and customer signals. Missing fields stay unknown, never empty.",
            "3. **Select the sample.** Age, customer, and affects-version rules are applied locally. Excluded bugs are listed with reasons in `selection.json`.",
            "4. **Build the comparison corpus.** Open and closed bugs are searched for duplicate and fix leads. Leads are not verdicts.",
            "5. **Investigate one bug per fresh agent.** Each investigator writes one assessment with requirements, evidence, validation, and a fix plan.",
            "6. **Compose and check.** The tool checks evidence shape, method matching, proof gates, and delivery eligibility. It writes this phase.",
            "7. **Hold or propose.** A comment is only `propose` when the inputs are complete. Otherwise it stays `review_required` or is `suppress`.",
            "8. **Handoff.** `02-fixes/` routes each finding to a pull request, documentation change, new issue, resolution, or blocked check. No write is performed.",
            "",
            "## Thresholds",
            "",
            f"- Duplicate close: {thresholds.get('duplicate', 0.85):.2f}",
            f"- Already-fixed close: {thresholds.get('fixed', 0.80):.2f}",
            "",
            "A score is a citation-strength measure, not a probability.",
            "",
            "## What this cannot promise",
            "",
            "- Reading code is not running the product.",
            "- A failed or incomplete search is not a negative result.",
            "- Customer-field coverage can be unknown even when labels and links were screened.",
            "- An open ticket, silence, or a missing PR does not establish that a bug persists.",
            "- The write phase needs fresh reads and its own approval.",
            "",
            f"Release: `{current_release}`. Evidence: {release_evidence or 'not supplied'}.",
            f"Selection query: `{jql}`.",
            "",
        ]
    )


def render_run_audit(
    packets: List[Packet],
    *,
    sample: Dict[str, Any],
    coverage: Dict[str, Any],
    meta: Dict[str, Any],
    current_release: str,
    release_evidence: str,
) -> str:
    excluded = sample.get("excluded") or []
    collection = coverage.get("collection") or {}
    failed = []
    for key, record in collection.items():
        searches = record.get("searches") or []
        errors = [item for item in searches if item.get("status") != "success"]
        if errors:
            failed.append((key, len(errors), len(searches), errors[0].get("error", "")))
    lines = [
        "# Run audit",
        "",
        "## Scope",
        "",
        f"- Release under review: `{current_release}`",
        f"- Evidence link: {release_evidence or 'not supplied'}",
        f"- Search: `{meta.get('jql', '')}`",
        f"- Input bugs: {coverage.get('inputIssues', 'unknown')}",
        f"- Eligible: {coverage.get('eligibleIssues', 'unknown')}",
        f"- Selected: {coverage.get('selectedIssues', len(packets))}",
        f"- Excluded: {len(excluded)}",
        f"- Comparison corpus: {meta.get('backlogSize', 'unknown')} records; closed included: {meta.get('backlogHasClosed', 'unknown')}",
        "",
        "## Exclusions",
        "",
        "The full list with one reason per bug is in `selection.json`.",
        "",
    ]
    if excluded:
        from collections import Counter

        reasons = Counter(_one_line(item.get("reason"), 200) for item in excluded)
        for reason, count in reasons.most_common():
            lines.append(f"- {count}: {reason}")
    else:
        lines.append("- None.")
    lines += [
        "",
        "## Collection failures",
        "",
    ]
    if failed:
        for key, error_count, total, error in failed:
            lines.append(
                f"- {key}: {error_count} of {total} GitHub searches failed. First error: {_one_line(error, 220)}"
            )
        lines.append("")
        lines.append("A failed search is not a zero result.")
    else:
        lines.append("- No failed collection searches recorded.")
    complete = int(meta.get("customerFieldsCompleteCount", 0) or 0)
    total = int(meta.get("counts", {}).get("packets", len(packets)) or len(packets))
    lines += [
        "",
        "## Customer-field coverage",
        "",
        f"- Complete mapped-field coverage: {complete} of {total} investigations.",
        "- Incomplete coverage means the customer fields could not be fully read, not that the ticket is customer-linked. Customer screening still used the `RHDH-Customer` label, RHDHSUPP/ACCOUNT links, and support keys in text.",
    ]
    if complete < total:
        lines.append(
            "- Comments stay `review_required` while coverage is incomplete; that is a hold, not permission to post."
        )
    lines += [
        "",
        "## Prose pass",
        "",
        "- Not recorded by this command. The workflow requires exactly one prose pass over the exact drafts before posting; record its result in the review notes.",
        "",
        "## Writes",
        "",
        "- `writes: []`. No Jira comment, link, assignment, transition, close, fix, PR, backport, or cluster mutation was performed.",
        "",
        "## Input hashes",
        "",
    ]
    for name, digest in sorted((meta.get("inputSha256") or {}).items()):
        lines.append(f"- `{name}`: `{digest}`")
    lines += [""]
    return "\n".join(lines)


def render_release(*, current_release: str, release_evidence: str, generated_at: str) -> str:
    return "\n".join(
        [
            "# Release under review",
            "",
            f"- Version: `{current_release}`",
            f"- Evidence: {release_evidence or 'not supplied'}",
            f"- Recorded: {generated_at}",
            "",
            "The tool records the supplied link; it does not verify the link's contents.",
            "Read the linked release record and the code anchors cited in each assessment before accepting a finding.",
            "",
            "Check code and documentation refs against the exact tag, commit, or release artifact under review.",
            "",
        ]
    )


def render_fixes_readme() -> str:
    return """# Fix review

[Open the review queue](../START-HERE.md) for the current disposition, local proposals and remaining work.

| Folder | Contents |
|---|---|
| `pull-requests/KEY/` | The case and plan for code, configuration, tests or documentation. |
| `events/KEY/REVISION-HASH/` | An immutable local result for one fix request. Open PROPOSAL.md for the target branch, change.patch for the diff, VERIFY.md for checks and backports/ for maintenance changes. receipt.json records the processed revision. |
| `new-bugs/KEY/` | A proposed follow-up issue. |
| `resolution/KEY/` | Evidence for closing or retargeting a bug, including holds. |
| `blocked/KEY/` | The attempted check and the missing evidence or access. |

The event worker checks each patch against its recorded branch tip. Replaying the same request reuses its receipt. Shared repositories and Jira stay read-only.
"""


def render_fixes_audit() -> str:
    return """# Local fix audit

[Review the queue](../START-HERE.md) for current proposals, tests and remaining decisions.
Each accepted fix event retains its repository, pinned branch, patch, verification and backport decisions beside its receipt.
The [triage snapshot](../01-triage/audit/manifest.json) records the inputs and external write count.
"""


def render_case(packet: Packet, ticket: Ticket) -> str:
    outcome = fix_outcome(packet)
    return "\n".join(
        [
            f"# {packet.key} — {packet.summary}",
            "",
            f"- Origin: `../../../{TRIAGE}/audit/bugs/{packet.key}.md`",
            f"- Verdict: `{packet.verdict}`",
            f"- Outcome: `{outcome}`",
            f"- Owner: {_owner(ticket)}",
            f"- Status: {_case_status(packet)}",
            f"- Action: {_case_action(packet)}",
            "",
            "## Boundary",
            "",
            "This case records the triage-time plan. See the [live review queue](../../../START-HERE.md) for later patches and verification.",
            "",
        ]
    )


def render_plan(packet: Packet) -> str:
    plan = packet.fix_plan or {}
    lines = [
        f"# Plan — {packet.key}",
        "",
        (
            "Resolution held. " + "; ".join(packet.verification_errors or [_post_reason(packet)])
            if packet.verdict == "unclear" and fix_outcome(packet) == "resolution"
            else _text(plan.get("approach"), "No fix plan recorded.")
        ),
        "",
        f"- Size: `{_text(plan.get('complexity'), 'unknown')}`",
        "",
        "## Areas",
        "",
    ]
    areas = _fix_areas(plan)
    lines += areas or ["- No product area applies."]
    lines += [
        "",
        "## Secondary actions",
        "",
    ]
    outcome = fix_outcome(packet)
    if outcome == "resolution" and packet.verdict == "unclear":
        lines.append("- " + packet.recommended_step)
    elif outcome == "resolution":
        lines.append(
            "- Review the cited resolution and decide whether to close, retarget, or verify."
        )
    elif outcome == "blocked":
        lines.append(
            "- Do the missing check in `../../../"
            + TRIAGE
            + "/audit/bugs/"
            + packet.key
            + ".md` first."
        )
    elif outcome == "docs":
        lines.append(
            "- Update the documentation and check the "
            f"{packet.current_release} page after the change."
        )
    elif outcome == "new-bugs":
        lines.append("- Draft the follow-up issue with its link to the original.")
    else:
        lines.append("- Run the named tests and attach the result in `VERIFY.md`.")
    lines += [""]
    return "\n".join(lines)


def write_phased_output(
    output_dir: Path,
    *,
    packets: List[Packet],
    tickets: Dict[str, Ticket],
    sample: Dict[str, Any],
    coverage: Dict[str, Any],
    meta: Dict[str, Any],
    generated_at: str,
    as_of: str,
    current_release: str,
    jql: str,
    thresholds: Dict[str, float],
    release_evidence: str,
    assessments_dir: str,
) -> None:
    triage = output_dir / TRIAGE
    fixes = output_dir / FIXES
    for directory in (
        triage,
        triage / "comments",
        triage / "audit",
        triage / "audit" / "bugs",
        triage / "audit" / "assessments",
        fixes,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    write_text(
        triage / "START-HERE.md",
        render_start_here(
            packets,
            tickets,
            as_of=as_of,
            current_release=current_release,
            release_evidence=release_evidence,
            excluded_count=len(sample.get("excluded") or []),
            corpus_size=int(meta.get("backlogSize", 0) or 0),
        ),
    )
    for packet in packets:
        write_text(triage / "comments" / f"{packet.key}.md", render_comment_file(packet))
        write_text(
            triage / "audit" / "bugs" / f"{packet.key}.md",
            render_bug_audit(packet, tickets[packet.key]),
        )
        if assessments_dir:
            source = Path(assessments_dir) / f"{packet.key}.json"
            if source.is_file():
                shutil.copyfile(source, triage / "audit" / "assessments" / f"{packet.key}.json")

    write_text(
        triage / "audit" / "METHOD.md",
        render_method(
            current_release=current_release,
            release_evidence=release_evidence,
            jql=jql,
            thresholds=thresholds,
        ),
    )
    write_text(
        triage / "audit" / "RUN.md",
        render_run_audit(
            packets,
            sample=sample,
            coverage=coverage,
            meta=meta,
            current_release=current_release,
            release_evidence=release_evidence,
        ),
    )
    write_text(
        triage / "audit" / "release.md",
        render_release(
            current_release=current_release,
            release_evidence=release_evidence,
            generated_at=generated_at,
        ),
    )
    write_json(triage / "audit" / "selection.json", sample)
    write_json(triage / "audit" / "manifest.json", meta)
    write_json(
        triage / "audit" / "packets.json",
        {
            "schemaVersion": 3,
            "dryRun": True,
            "generatedAt": generated_at,
            "currentRelease": current_release,
            "meta": meta,
            "packets": [
                {
                    **packet.to_dict(),
                    "fixVersions": tickets[packet.key].fix_versions,
                    "fixVersionsEmpty": tickets[packet.key].fix_versions_empty,
                    "releaseNoteFields": tickets[packet.key].release_note_fields,
                    "reporter": {
                        "displayName": tickets[packet.key].reporter,
                        "accountId": tickets[packet.key].reporter_account_id,
                    },
                }
                for packet in packets
            ],
        },
    )

    summary = {
        "schemaVersion": 1,
        "input": coverage["inputIssues"],
        "eligible": sample.get("eligibleCount"),
        "selected": len(packets),
        "excluded": len(sample.get("excluded", [])),
        "investigations": _investigation_counts(packets),
        "verdicts": _verdict_counts(packets),
        "delivery": _delivery_counts(packets),
        "fixPlans": _outcome_counts(packets),
        "generatedDiffsAtTriage": 0,
    }
    write_json(output_dir / "run.json", summary)
    write_text(fixes / "README.md", render_fixes_readme())
    write_text(fixes / "AUDIT.md", render_fixes_audit())
    for packet in packets:
        outcome = fix_outcome(packet)
        case = fixes / ("pull-requests" if outcome == "docs" else outcome) / packet.key
        case.mkdir(parents=True, exist_ok=True)
        write_text(case / "CASE.md", render_case(packet, tickets[packet.key]))
        write_text(case / "PLAN.md", render_plan(packet))
    refresh_review(output_dir)
