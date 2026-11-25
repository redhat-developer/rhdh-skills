"""Record the furthest evidenced local outcome for every selected issue."""

import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

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
        if "nextActions" in row:
            assignments = row["nextActions"]
            if not isinstance(assignments, list) or not assignments:
                raise ValueError(f"{key} needs at least one owner and action")
            case["nextActions"] = [
                {field: required(assignment, field) for field in ("owner", "action")}
                for assignment in assignments
            ]
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
        original = packet.get("proposedComment")
        if original:
            for field in ("finding", "next"):
                value = case[field]
                if len(value) > 320 or len(value.splitlines()) != 1 or "://" in value:
                    raise ValueError(
                        f"{key} needs brief single-line prose in {field}; cite URLs in evidence"
                    )
            refs = {item["ref"] for item in packet["evidence"]}
            ref = next(
                (value for value in packet.get("validation", {}).get("refs", []) if value in refs),
                key,
            )
            citation = "Fix: " + ref_link(fix_link) if fix_link else "Evidence: " + ref_link(ref)
            if packet.get("verdict") == "duplicate":
                citation = "Canonical issue: " + ref_link(packet["target"])
            case["proposedComment"] = "\n".join(
                (
                    _linked_text(case["finding"]),
                    citation,
                    _linked_text(case["next"]),
                    f"Triage reference: `{packet['commentPlan']['reference']}`.",
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
