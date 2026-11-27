"""Record the furthest evidenced local outcome for every selected issue."""

import hashlib
import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote

from .comments import comment_footer
from .cycle import render_cycle_index
from .events import required
from .layout import refresh_review
from .model import as_text, verified_support_cases
from .policy import CLOSE_ACTIONS, _linked_text, ref_link


def atomic_write(path, data):
    with NamedTemporaryFile(dir=path.parent, delete=False) as target:
        target.write(data)
    Path(target.name).replace(path)


def release_summary(packet, stage, run):
    if stage == "existing_fix":
        return f"Verified in RHDH {packet['currentRelease']}."
    versions = packet.get("fixVersions", [])
    release = (
        "Jira fix version: " + ", ".join(versions) + "."
        if versions
        else "Exact fix version unconfirmed."
    )
    if stage != "patch":
        return release
    bases, ports, skipped, pending = set(), set(), set(), set()
    for receipt in (run / "02-fixes/events" / packet["key"]).glob("*/proposal.json"):
        proposal = json.loads(receipt.read_bytes())
        if proposal.get("branch"):
            bases.add(proposal["branch"])
        skipped.update(
            item["branch"] for item in proposal.get("backports", []) if item["decision"] == "skip"
        )
        pending.update(
            item["branch"]
            for item in proposal.get("backports", [])
            if item["decision"] == "undetermined"
        )
        ports.update(
            item["branch"]
            for item in proposal.get("backports", [])
            if item["decision"] == "propose"
        )
    for label, branches in (
        ("Proposed target", bases),
        ("Proposed backport", ports),
        ("Backport pending assessment", pending - ports),
        ("Backport skipped", skipped - ports - pending),
    ):
        if branches:
            release += f" {label}: " + ", ".join(sorted(branches)) + "."
    return release


def jira_field_plan(packet, stage, row, proposals, inputs):
    """Build a local field preview from the issue snapshot and verified fix targets."""
    fields, messages = {}, []
    if stage not in {"patch", "existing_fix"}:
        return fields, messages
    if (
        packet.get("fixVersionsEmpty")
        and not packet.get("fixVersions")
        and "projectVersions" in row
    ):
        catalog = json.loads((inputs / required(row, "projectVersions")).read_bytes())
        if not isinstance(catalog, list):
            raise ValueError("projectVersions must contain the Jira project versions array")
        eligible = {
            required(item, "name")
            for item in catalog
            if item.get("archived") is False and item.get("released") is (stage == "existing_fix")
        }
        if stage == "existing_fix":
            targets = {packet.get("fix", {}).get("release")}
        else:
            by_branch = {}
            for proposal in proposals:
                for target in [
                    proposal,
                    *(b for b in proposal["backports"] if b["decision"] == "propose"),
                ]:
                    branch = (proposal["repository"], target["branch"])
                    by_branch.setdefault(branch, set()).add(
                        target.get("releaseTarget", {}).get("version")
                    )
            targets = (
                set().union(*by_branch.values())
                if all(len(v) == 1 for v in by_branch.values())
                else set()
            )
        if targets and targets <= eligible:
            fields["Fix Version/s"] = sorted(targets)
            messages.append("Proposed fix versions: " + ", ".join(sorted(targets)) + ".")
    note_fields, note_message = release_note_plan(packet, row, inputs)
    fields.update(note_fields)
    messages.append(note_message)
    return fields, messages


def release_note_plan(packet, row, inputs):
    note = row.get("releaseNote")
    if not isinstance(note, dict):
        raise ValueError(
            f"{packet.get('key', 'fix outcome')} needs releaseNote wording or a reason"
        )
    observed = packet.get("releaseNoteFields", {})
    decision = note.get("decision", "draft")
    existing_type = observed.get("Release Note Type")
    if isinstance(existing_type, dict):
        existing_type = existing_type.get("value")
    if decision == "retain":
        if not as_text(observed.get("Release Note Text")).strip():
            raise ValueError("retaining a release note requires existing Jira note text")
        return (
            {},
            f"Existing {existing_type or 'release'} note retained. {required(note, 'reason')}",
        )
    if decision == "internal":
        return {}, f"Release note unnecessary for this internal change. {required(note, 'reason')}"
    if decision != "draft":
        raise ValueError("releaseNote.decision must be draft, retain or internal")

    text = required(note, "text")
    note_type = required(note, "type") if "type" in note else None
    if any(len(value.splitlines()) > 1 for value in [text, note_type or ""]):
        raise ValueError("use one line for the proposed release note")
    draft = {
        "Release Note Text": text,
        "Release Note Type": note_type,
        "Release Note Status": "Proposed",
    }
    metadata = {}
    if row.get("releaseNoteEditMeta"):
        path = inputs / required(row, "releaseNoteEditMeta")
        if path.is_file():
            metadata = json.loads(path.read_bytes())["fields"]
    options = {
        field.get("name"): {opt.get("value") for opt in field.get("allowedValues", [])}
        for field in metadata.values()
        if "set" in field.get("operations", ["set"])
    }
    pending = []
    for name, value in draft.items():
        current = observed.get(name)
        if name != "Release Note Text" and isinstance(current, dict):
            current = current.get("value")
        if (
            name not in observed
            or current not in (None, "", value)
            or name not in options
            or (name != "Release Note Text" and (not value or value not in options[name]))
        ):
            pending.append(name)
    if pending:
        suggestion = f"Suggested type {note_type}. " if note_type else ""
        return (
            {},
            f"Release note draft: {text} {suggestion}Suggested status Proposed. Jira field review pending for {', '.join(pending)}.",
        )
    return draft, f"Release note proposed ({note_type}): {text}"


def command_finish(args):
    run = Path(args.out)
    source = Path(args.input)
    packets = json.loads((run / "01-triage/audit/packets.json").read_bytes())["packets"]
    rows = json.loads(source.read_bytes())
    cases = {}
    proofs = {}
    if not isinstance(rows, list):
        raise ValueError("expected an array of follow-through results")
    findings = {p["key"]: p for p in packets}
    for row in rows:
        key = required(row, "key")
        if key not in findings or key in cases:
            raise ValueError("unexpected or duplicate issue: " + key)
        packet = findings[key]
        case = {
            field: required(row, field) for field in ("stage", "finding", "verification", "next")
        }
        if "resolution" in row:
            case["resolution"] = required(row, "resolution")
        stage = case["stage"]
        classification = packet.get("investigation", {}).get("classification", {})
        review_type = classification.get("kind") in {"feature", "task", "uncertain"}
        if review_type and stage not in {"blocked", "classification_review"}:
            raise ValueError(f"{key} requires human classification review")
        fix_link = ""
        if stage == "patch":
            if not any(
                (path.parent / "change.patch").is_file()
                and json.loads(path.read_bytes()).get("outcome") == "review_patch"
                for path in (run / "02-fixes/events" / key).glob("*/receipt.json")
            ):
                raise ValueError(f"{key} needs a verified patch receipt")
        elif stage == "existing_fix":
            fix = packet.get("fix", {})
            errors = packet["verificationErrors"]
            coverage_hold = (
                packet["verdict"] == "unclear"
                and errors
                and all(
                    "customer-field read coverage is incomplete" in error
                    or error == "customer-linked ticket cannot receive a close proposal"
                    for error in errors
                )
            )
            proof_refs = packet.get("proof", {}).get("releaseContains", {}).get("refs", [])
            direct = {
                (item["type"], item["ref"])
                for item in packet.get("evidence", [])
                if item.get("strength") == "direct"
            }
            fix_link = next((fix[t] for t in ("pr", "commit") if (t, fix.get(t)) in direct), "")
            if not (
                ((packet["verdict"] == "already_fixed" and not errors) or coverage_hold)
                and all(fix.get(k) for k in ("released", "merged", "containedInReviewRelease"))
                and fix_link
                and any(("release_note", ref) in direct for ref in proof_refs)
                and packet.get("validation", {}).get("result") == "resolved"
            ):
                raise ValueError(f"{key} needs verified release inclusion")
        elif stage == "verified_resolution":
            if (
                packet["verdict"] not in {"duplicate", "no_longer_valid"}
                or packet["verificationErrors"]
            ):
                raise ValueError(f"{key} needs a verified duplicate or obsolete finding")
        elif stage == "ready_to_close":
            if (
                packet["action"] not in CLOSE_ACTIONS
                or packet["verificationErrors"]
                or packet["commentPlan"]["status"] != "propose"
            ):
                raise ValueError(f"{key} has a closure or delivery hold")
        elif stage == "classification_review" and review_type:
            case["next"] = "Triage owner: review the issue type before scheduling work."
        elif stage == "blocked":
            case["blocker"] = required(row, "blocker")
        else:
            raise ValueError("unknown follow-through stage: " + stage)
        evidence = (source.parent / required(row, "evidence")).resolve()
        if not evidence.is_relative_to(source.parent.resolve()) or evidence.suffix not in {
            ".md",
            ".txt",
            ".json",
            ".log",
        }:
            raise ValueError("expected a local evidence document beside the results")
        data = evidence.read_bytes()
        if not data.strip():
            raise ValueError("empty verification evidence")
        digest = hashlib.sha256(data).hexdigest()
        path = Path("01-triage/audit/followthrough") / f"{key}-{digest[:12]}{evidence.suffix}"
        case["evidence"] = path.as_posix()
        if "nextActions" in row:
            assignments = row["nextActions"]
            if not isinstance(assignments, list) or not assignments:
                raise ValueError(f"{key} needs at least one owner and action")
            case["nextActions"] = []
            for assignment in assignments:
                action = {field: required(assignment, field) for field in ("owner", "action")}
                if "pr" in assignment:
                    action["pr"] = required(assignment, "pr")
                if "links" in assignment:
                    links = assignment["links"]
                    if not isinstance(links, list):
                        raise ValueError(f"{key} needs a list of action links")
                    action["links"] = []
                    for item in links:
                        label, link_path = required(item, "label"), Path(required(item, "path"))
                        if str(link_path) == "@evidence":
                            action["links"].append({"label": label, "path": case["evidence"]})
                            continue
                        target = (run / link_path).resolve()
                        if (
                            link_path.is_absolute()
                            or not target.is_relative_to(run.resolve())
                            or not target.is_file()
                        ):
                            raise ValueError(
                                f"{key} action link must identify a file in the review directory"
                            )
                        action["links"].append(
                            {"label": label, "path": target.relative_to(run.resolve()).as_posix()}
                        )
                case["nextActions"].append(action)
        if stage == "classification_review":
            case["nextActions"] = [
                {
                    "owner": "Triage owner",
                    "action": "Review the proposed issue type",
                    "links": [{"label": "Evidence", "path": case["evidence"]}],
                }
            ]
        if fix_link:
            case["fixedNextStep"] = f"{ref_link(fix_link)} — {_linked_text(case['next'])}"
        proposals = [
            json.loads(path.read_bytes())
            for path in (run / "02-fixes/events" / key).glob("*/proposal.json")
        ]
        fields, messages = jira_field_plan(packet, stage, row, proposals, source.parent)
        signals = packet.get("customerSignals", [])
        support_cases = verified_support_cases(signals)
        if support_cases:
            case["supportCases"] = support_cases
            messages.append(
                "Support coordination required. Review "
                + ", ".join(support_cases)
                + " with the support owner before customer communication or closure."
            )
        elif signals:
            messages.append("Customer context recorded. A support-case link has not been verified.")
        if review_type:
            messages.append(
                f"Human classification review requested ({classification['kind']}): {classification['basis']}"
            )
        case["proposedJiraFields"] = fields
        case["jiraFieldSummary"] = messages
        original = packet.get("proposedComment")
        if original:
            outcome_field = "resolution" if "resolution" in case else "finding"
            for field in (outcome_field, "verification", "next"):
                value = case[field]
                if "://" in value:
                    raise ValueError(f"{key} needs plain prose in {field}; cite URLs in evidence")
            refs = {item["ref"] for item in packet["evidence"]}
            ref = next(
                (value for value in packet.get("validation", {}).get("refs", []) if value in refs),
                key,
            )
            if "citationRef" in row:
                ref = required(row, "citationRef")
                if ref not in refs:
                    raise ValueError(
                        f"{key} citationRef must reference evidence in the triage packet"
                    )
            citation = "Fix: " + ref_link(fix_link) if fix_link else "Evidence: " + ref_link(ref)
            if not fix_link and any(
                item["ref"] == ref and item["type"] == "doc" for item in packet["evidence"]
            ):
                citation = "Related guidance: " + ref_link(ref)
            if packet.get("verdict") == "duplicate":
                citation = "Canonical issue: " + ref_link(packet["target"])
            public_prs = row.get("reviewPRs", [])
            verified_prs = {
                item["ref"]
                for item in packet["evidence"]
                if item["type"] == "pr" and item.get("strength") == "direct"
            }
            if not isinstance(public_prs, list) or not all(
                isinstance(url, str)
                and url in verified_prs
                and re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/pull/[1-9]\d*", url)
                for url in public_prs
            ):
                raise ValueError(f"{key} reviewPRs must be directly evidenced GitHub pull requests")
            bullets = []
            pending_prs = dict.fromkeys(public_prs)
            for assignment in case.get("nextActions", []):
                text = _linked_text(assignment["action"]).rstrip(".")
                owner = _linked_text(assignment["owner"])
                pr = assignment.get("pr")
                if pr:
                    if pr not in public_prs:
                        raise ValueError(f"{key} action PR must be a verified reviewPR")
                    pending_prs.pop(pr, None)
                    target = ref_link(pr)
                else:
                    links = [
                        item
                        for item in assignment.get("links", [])
                        if item["path"] != f"01-triage/comments/{key}.md"
                    ]
                    target = ""
                    if links:
                        item = links[0]
                        target = f"[{_linked_text(item['label'])}](../../{quote(item['path'])})"
                bullets.append(f"- **{owner}** — {text}" + (f": {target}" if target else "."))
            if not case.get("nextActions"):
                bullets.append("- " + _linked_text(case["next"]))
            bullets.extend(f"- Review pull request: {ref_link(url)}" for url in pending_prs)
            if packet.get("verdict") == "duplicate":
                bullets.append("- " + citation)
            tldr = _linked_text(case[outcome_field]) + " " + release_summary(packet, stage, run)
            if "Fix Version/s" in fields:
                tldr = tldr.replace("Exact fix version unconfirmed.", "").strip()
            if messages:
                tldr += "\n\n" + "\n\n".join(_linked_text(message) for message in messages)
            if "featureRequest" in row and not review_type:
                capability = required(row, "featureRequest")
                reporter = packet.get("reporter") or {}
                account = reporter.get("accountId")
                name = reporter.get("displayName")
                recipient = "Reporter"
                if account and name:
                    recipient = "@" + _linked_text(name)
                    case["featureRequesterMention"] = {
                        "type": "mention",
                        "attrs": {"id": account, "text": "@" + name},
                    }
                tldr += f" {recipient}, please open a feature request for {_linked_text(capability)} if you still need it."
            case["proposedComment"] = "\n\n".join(
                (
                    f"**Re: {ref_link(key)}** · {_linked_text(packet['summary'])}",
                    "### TL;DR",
                    tldr,
                    "### Next steps",
                    case.get("fixedNextStep") or "\n".join(bullets) or _linked_text(case["next"]),
                    comment_footer(packet["commentPlan"]["reference"]),
                )
            )
            case["delivery"] = (
                "suppress" if packet["commentPlan"]["status"] == "suppress" else "review_required"
            )
        observed = packet.get("status") or "Unknown"
        transition = {"observed": observed, "applied": False}
        if observed.casefold() == "in review":
            transition["state"] = "already_in_review"
        elif (
            case.get("proposedComment")
            and case["delivery"] != "suppress"
            and stage not in {"blocked", "classification_review"}
            and observed != "Unknown"
        ):
            transition.update(state="proposed_after_comment", target="In Review")
        else:
            transition["state"] = "no_action"
        case["jiraTransition"] = transition
        proofs[path] = data
        cases[key] = case
    if cases.keys() != findings.keys():
        raise ValueError("expected one evidenced outcome for every selected bug")
    summary_path = run / "run.json"
    summary = json.loads(summary_path.read_bytes())
    summary["cases"] = cases
    for path, data in proofs.items():
        target = run / path
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, data)
    atomic_write(summary_path, (json.dumps(summary, indent=2) + "\n").encode())
    for key, case in cases.items():
        if case.get("proposedComment"):
            atomic_write(
                run / "01-triage/comments" / f"{key}.md", (case["proposedComment"] + "\n").encode()
            )
    refresh_review(run)
    index = render_cycle_index(run)
    if index is not None:
        atomic_write(run.parent / "START-HERE.md", index.encode())
    return 0
