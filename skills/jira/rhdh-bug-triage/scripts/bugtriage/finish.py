"""Record the furthest evidenced local outcome for every selected issue."""

import hashlib
import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote

from .events import required
from .layout import refresh_review
from .policy import CLOSE_ACTIONS, _linked_text, ref_link


def atomic_write(path, data):
    with NamedTemporaryFile(dir=path.parent, delete=False) as target:
        target.write(data)
    Path(target.name).replace(path)


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
                and all("customer-field read coverage is incomplete" in error for error in errors)
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
            if public_prs:
                citation = " · ".join(ref_link(url) for url in dict.fromkeys(public_prs))
                if fix_link and fix_link not in public_prs:
                    citation += " · Fix: " + ref_link(fix_link)
            elif stage == "patch":
                citation = "Local proposal only. " + citation
            bullets = []
            for assignment in case.get("nextActions", []):
                bullet = f"- **{_linked_text(assignment['owner'])}** — {_linked_text(assignment['action'])}"
                links = [
                    f"[{_linked_text(item['label'])}](../../{quote(item['path'])})"
                    for item in assignment.get("links", [])
                    if item["path"] != f"01-triage/comments/{key}.md"
                ]
                if links:
                    bullet += " Local files: " + " · ".join(links)
                bullets.append(bullet)
            case["proposedComment"] = "\n\n".join(
                (
                    f"**Re: {ref_link(key)}** · {_linked_text(packet['summary'])}",
                    "### Outcome",
                    _linked_text(case[outcome_field]),
                    "### Checks",
                    _linked_text(case["verification"]),
                    "### Review",
                    citation,
                    "### Who does what next",
                    "\n".join(bullets) or _linked_text(case["next"]),
                    f"Triage reference: `{packet['commentPlan']['reference']}`.",
                    "*rhdh-agentic-bug-triager · AI-generated. Check for accuracy.*",
                )
            )
            case["delivery"] = (
                "suppress" if packet["commentPlan"]["status"] == "suppress" else "review_required"
            )
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
    return 0
