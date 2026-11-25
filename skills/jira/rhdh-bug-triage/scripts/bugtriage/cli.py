"""Command-line surface for the RHDH aged-bug triage skill.

Every command is read-only. ``run`` refuses to accept an apply flag because no
write path exists; proposed actions are files under the output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import List, Optional

from .brief import write_briefs
from .collect import CollectConfig, collect
from .comments import DEFAULT_COOLDOWN_DAYS
from .evaluate import write_evaluation
from .events import command_event, command_trigger
from .forge import ForgeAdapterError
from .jira import (
    JiraAdapterError,
    build_backlog,
    export_from_acli,
    load_tickets_from_acli,
    search_acli,
    write_acli_probe,
)
from .layout import fix_outcome
from .model import (
    DEFAULT_AGED_DAYS,
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_SEED,
    load_export,
)
from .report import now_iso, write_json
from .run import (
    RunConfig,
    RunError,
    build_sample_manifest,
    default_jql,
    parse_as_of,
    run,
)
from .selection import Control, SelectionConfig
from .verification import collect_verification


def _controls(values: Optional[List[str]]) -> List[Control]:
    controls = []
    for value in values or []:
        key, _, label = value.partition("=")
        if key.strip():
            controls.append(Control(key=key.strip(), label=label.strip()))
    return controls


def _load_tickets(args: argparse.Namespace):
    if args.source == "acli":
        return load_tickets_from_acli(
            args.jql or default_jql(args.aged_days, args.scope),
            field_names=_field_names(args.field_names),
        )
    if not args.input:
        raise RunError("--input is required when --source=export")
    return load_export(args.input)


def _field_names(path: Optional[str]) -> Optional[dict]:
    if not path:
        return None
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(document, list):
        if not all(
            isinstance(row, dict)
            and isinstance(row.get("id"), str)
            and isinstance(row.get("name"), str)
            for row in document
        ):
            raise RunError("expected Jira field metadata with id and name")
        document = {row["id"]: row["name"] for row in document}
    if (
        not isinstance(document, dict)
        or not document
        or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in document.items())
    ):
        raise RunError("--field-names must contain the tenant-resolved field-ID to name mapping")
    return document


def command_progress(args):
    inventory = Path(args.inventory).read_bytes()
    expected = set(json.loads(inventory)["keys"])
    digest = hashlib.sha256(inventory).hexdigest()
    states = {}
    for directory in args.run:
        audit = Path(directory) / "01-triage" / "audit"
        result = json.loads((audit / "packets.json").read_text())
        if result["meta"]["coverage"].get("inventoryHash") != digest:
            raise RunError("batch comes from a different inventory")
        sample = json.loads((audit / "selection.json").read_text())
        rows = [(row["key"], "excluded") for row in sample["excluded"]]
        rows.extend(
            (row["key"], row["investigation"].get("status") or "pending")
            for row in result["packets"]
        )
        for key, status in rows:
            if key not in expected or key in states:
                raise RunError("overlapping or out-of-inventory batch")
            states[key] = status if status in {"excluded", "completed", "blocked"} else "pending"
    print(
        json.dumps(
            {
                state: sorted(key for key in expected if states.get(key, "pending") == state)
                for state in ("completed", "blocked", "excluded", "pending")
            },
            indent=2,
        )
    )
    return 0


def command_inventory(args):
    path = Path(args.out)
    jql = (
        default_jql(DEFAULT_AGED_DAYS, "all-open")
        if args.project == "RHDHBUGS"
        else "project = RHDHSUPP AND statusCategory != Done ORDER BY updated ASC, key ASC"
    )
    rows = search_acli(jql, fields="key,status")
    keys = [row["key"] for row in rows]
    if len(set(keys)) != len(keys) or any(
        not re.fullmatch(args.project + r"-\d+", key) for key in keys
    ):
        raise RunError("duplicate or out-of-scope inventory key")
    with path.open("x", encoding="utf-8") as handle:
        json.dump(
            {"project": args.project, "jql": jql, "observedAt": now_iso(), "keys": keys},
            handle,
            indent=2,
        )
    print(f"{len(keys)} inventory keys in {path}")
    return 0


def command_fetch(args: argparse.Namespace) -> int:
    path = Path(args.out)
    if path.exists():
        raise RunError(f"refusing to overwrite export: {path}")
    jql = args.jql
    expected = None
    if args.inventory:
        inventory_bytes = Path(args.inventory).read_bytes()
        inventory = json.loads(inventory_bytes)
        if inventory["project"] != "RHDHBUGS" or args.batch < 1 or args.size < 1:
            raise RunError("bug inventory and positive batch and size required")
        start = (args.batch - 1) * args.size
        expected = inventory["keys"][start : start + args.size]
        if not expected or not all(
            isinstance(k, str) and re.fullmatch(r"RHDHBUGS-\d+", k) for k in expected
        ):
            raise RunError("batch is empty or contains invalid keys")
        jql = "key IN (" + ", ".join(expected) + ") ORDER BY key ASC"
    document = export_from_acli(jql, field_names=_field_names(args.field_names))
    if expected is not None:
        if sorted(row["key"] for row in document["issues"]) != sorted(expected):
            raise RunError("Jira did not return every requested inventory key")
        document["provenance"].update(
            inventoryHash=hashlib.sha256(inventory_bytes).hexdigest(),
            inventoryObservedAt=inventory["observedAt"],
            inventorySize=len(inventory["keys"]),
            batch=args.batch,
        )
    write_json(path, document)
    print(f"Fetched {len(document['issues'])} complete issue record(s) into {path}")
    return 0


def command_select(args: argparse.Namespace) -> int:
    as_of = parse_as_of(args.as_of)
    tickets = _load_tickets(args)
    jql = args.jql or default_jql(args.aged_days, args.scope)
    config = SelectionConfig(
        size=args.size,
        aged_days=args.aged_days,
        seed=args.seed,
        controls=_controls(args.control),
        current_release=args.current_release,
        scope=args.scope,
        all_tickets=args.all,
    )
    if (
        args.batch < 1
        or args.batch > 1
        and (args.all or args.control or not args.input or args.source != "export")
    ):
        raise RunError("numbered continuation requires a fixed export without --all or controls")
    if args.batch > 1 and not args.as_of:
        raise RunError("use the first batch's --as-of date for continuation")
    config.size *= args.batch
    sample = build_sample_manifest(tickets, config, as_of, jql)
    if args.batch > 1:
        sample["tickets"] = sample["tickets"][(args.batch - 1) * args.size :]
    sample.update(batch=args.batch, size=args.size)
    if args.out:
        write_json(Path(args.out), sample)
    if args.json:
        print(json.dumps(sample, indent=2))
    else:
        print(
            f"Selected {len(sample['tickets'])} ticket(s) from "
            f"{sample['eligibleCount']} eligible in a backlog of {len(tickets)}."
        )
        for entry in sample["tickets"]:
            kind = entry["kind"] + (
                f" ({entry['controlLabel']})" if entry.get("controlLabel") else ""
            )
            print(f"  {entry['key']:<20} {kind:<20} {entry['stratum']}")
        if args.out:
            print(f"Wrote {args.out}")
    return 0


def command_collect(args: argparse.Namespace) -> int:
    written = collect(
        CollectConfig(
            input_path=args.input,
            sample_path=args.sample,
            output_dir=args.out,
            forge_cache=args.forge_cache,
            use_gh=args.gh,
            repos=args.repo,
            backlog_path=args.backlog or "",
            jira_search=args.jira_search,
            max_queries=args.max_queries,
            query_limit=args.query_limit,
            hydrate_limit=args.hydrate_limit,
            field_names=_field_names(args.field_names),
        )
    )
    if args.json:
        print(json.dumps({"ok": True, "written": written}, indent=2))
    else:
        print(f"Collected evidence for {len(written)} ticket(s) into {args.out}")
        for key in sorted(written):
            print(f"  {key}: {written[key]}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    result = run(
        RunConfig(
            input_path=args.input,
            output_dir=args.out,
            sample_path=args.sample or "",
            assessments_dir=args.assessments or "",
            current_release=args.current_release,
            as_of=args.as_of,
            aged_days=args.aged_days,
            size=args.size,
            seed=args.seed,
            controls=_controls(args.control),
            backlog_path=args.backlog or "",
            jql=args.jql or "",
            comment_cooldown_days=args.comment_cooldown_days,
            scope=args.scope,
            all_tickets=args.all,
            release_evidence=args.release_evidence,
            evidence_dir=args.evidence or "",
            verification_dir=args.verification or "",
            require_investigation=args.require_investigation,
            require_fix_plan=args.require_fix_plan,
        )
    )
    counts = result.manifest["counts"]
    summary = {
        "ok": True,
        "dryRun": True,
        "output": str(result.output_dir),
        "packets": counts["packets"],
        "withEvidence": counts["withEvidence"],
        "closeProposals": counts["closeProposals"],
        "customerLinked": counts["customerLinked"],
        "surfacedRecommendations": counts["surfacedRecommendations"],
        "abstained": counts["abstained"],
        "verdicts": _count(result.packets, "verdict"),
        "actions": _count(result.packets, "action"),
        "draftComments": counts["draftComments"],
        "delivery": result.manifest["commentPolicy"]["counts"],
        "comparisonOutcomes": dict(
            Counter(c["relationship"] for p in result.packets for c in p.comparisons)
        ),
        "scopedFixStates": dict(
            Counter(p.fix_evidence["state"] for p in result.packets if p.fix_evidence)
        ),
        "investigationStates": result.manifest["investigationStates"],
        "fixOutcomes": dict(Counter(fix_outcome(packet) for packet in result.packets)),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Dry run finished: {counts['packets']} bug(s) in {result.output_dir}")
        print("Nothing was posted to Jira; no bugs were closed and no PRs were created.")
        for packet in result.packets:
            print(
                f"  {packet.key}  {packet.verdict}  delivery={packet.comment_plan.get('status', 'unknown')}"
            )
        print(
            f"Draft comments: {counts['draftComments']} · advisory closure recommendations: {counts['closeProposals']}"
        )
        print(f"Comment delivery: {result.manifest['commentPolicy']['counts']}")
        print(f"Fix outcomes: {dict(Counter(fix_outcome(packet) for packet in result.packets))}")
        print(
            "Open 01-triage/START-HERE.md first. Exact drafts are in 01-triage/comments/, "
            "proof is in 01-triage/audit/, and the fix handoff is in 02-fixes/. "
            "01-triage/audit/packets.json holds the machine record, inputs and hashes."
        )
    return 0


def _count(packets, attribute: str) -> dict:
    counts: dict = {}
    for packet in packets:
        value = getattr(packet, attribute)
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def command_brief(args: argparse.Namespace) -> int:
    written = write_briefs(
        input_path=args.input,
        sample_path=args.sample,
        output_dir=args.out,
        evidence_dir=args.evidence or "",
    )
    print(f"Wrote {len(written)} investigator brief(s) into {args.out}")
    print("Give one brief per fresh-context investigator; each writes assessments/KEY.json.")
    return 0


def command_backlog(args: argparse.Namespace) -> int:
    if not args.search_jql and not args.full_jql:
        raise RunError("backlog needs at least one --search-jql or --full-jql part")
    path = Path(args.out)
    if path.exists():
        raise RunError(f"refusing to overwrite backlog: {path}")
    document = build_backlog(
        search_jqls=list(args.search_jql or []),
        full_jqls=list(args.full_jql or []),
        field_names=_field_names(args.field_names),
        as_of=now_iso(),
    )
    write_json(path, document)
    parts = document["provenance"]["parts"]
    print(f"Built a {len(document['issues'])}-record backlog from {len(parts)} part(s) into {path}")
    for part in parts:
        print(f"  {part['level']:<13} {part['count']:>5} records — {part['jql'][:80]}")
    return 0


def command_evaluate(args: argparse.Namespace) -> int:
    evaluation, rendered = write_evaluation(
        args.packets,
        args.truth,
        output_path=args.out or "",
        strict=args.strict,
    )
    if args.json:
        print(json.dumps(evaluation.to_dict(), indent=2))
    else:
        print(rendered)
    if args.strict:
        return 0 if evaluation.strict_passed else 1
    return 0


def command_template(args: argparse.Namespace) -> int:
    from .run import load_sample_manifest

    sample = load_sample_manifest(args.sample)
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    written = []
    skipped = []
    for entry in sample.get("tickets", []):
        key = entry["key"]
        path = output / f"{key}.json"
        if path.exists() and not args.force:
            skipped.append(key)
            continue
        write_json(
            path,
            {
                "key": key,
                "_instructions": (
                    "Investigate this bug until you can fill in every field below. "
                    "'Unknown' is an honest answer, but only after you have tried to "
                    "settle it read-only. Saying a bug is still valid (or no longer "
                    "valid) requires evidence tied to the exact release under review. "
                    "Every piece of evidence needs a type, a link or issue key, a "
                    "sentence on why it matters, and a strength (direct|strong|"
                    "supporting). Never make up a confidence number — the tool "
                    "computes it from your citations. Recommending a close also needs "
                    "two independent reviews that agree. Every bug needs a fixPlan: "
                    "what a fix would change, where it would land, and how big it is "
                    "(for duplicate/already-fixed/no-longer-valid, describe the "
                    "resolution action instead and use complexity 'none'). "
                    "Optionally set handoff.outcome to pull_request, docs, "
                    "new_bug, resolution or blocked when the default routing "
                    "would put the case in the wrong phase."
                ),
                "verdict": "",
                "duplicateOf": "",
                "comparisons": [],
                "investigation": {
                    "status": "not_started",
                    "release": "",
                    "scope": "",
                    "mechanism": "",
                    "requirements": [],
                    "blocker": "",
                },
                "evidence": [],
                "proof": {},
                "validation": {
                    "release": "",
                    "method": "",
                    "result": "unknown",
                    "summary": "",
                    "refs": [],
                },
                "fixPlan": {
                    "approach": "",
                    "areas": [
                        {
                            "repository": "owner/repo",
                            "paths": ["path/that/would/change"],
                        }
                    ],
                    "complexity": "",
                    "refs": [],
                },
                "handoff": {
                    "outcome": "",
                    "reason": "",
                },
                "fix": {
                    "pr": "",
                    "commit": "",
                    "release": "",
                    "released": False,
                    "merged": False,
                    "coversWholeIssue": False,
                    "reviewRelease": "",
                    "containedInReviewRelease": False,
                },
                "fixEvidence": {
                    "state": "not_assessed",
                    "scenario": "",
                    "covered": [],
                    "unverified": [],
                    "incorporation": {},
                    "validation": {},
                },
                "repro": {"result": "not_run", "release": "", "notes": ""},
                "review": {"independentPasses": 0, "agree": False},
                "notes": "",
                "comment": "",
                "recommendedStep": "",
                "followUp": {"priorCommentId": "", "state": "unknown", "evidence": []},
            },
        )
        written.append(key)
    print(f"Wrote {len(written)} assessment template(s) to {output}")
    if skipped:
        print(f"Skipped {len(skipped)} existing file(s); pass --force to overwrite")
    return 0


def command_verify(args: argparse.Namespace) -> int:
    result = collect_verification(args.plan, args.out)
    print(
        json.dumps(
            {
                "dryRun": True,
                "keys": result["keys"],
                "reads": len(result["reads"]),
                "failedReads": sum(r["status"] == "failed" for r in result["reads"]),
                "output": args.out,
                "verdict": "requires_agent_inspection",
                "sourceSystemWrites": [],
            },
            indent=2,
        )
    )
    return 0


def command_check(args: argparse.Namespace) -> int:
    probe = write_acli_probe()
    gh_path = shutil.which("gh")
    report = {
        "python": platform.python_version(),
        "acli": probe,
        "gh": {"installed": bool(gh_path), "path": gh_path or ""},
        "dryRunOnly": True,
        "nextStep": (
            "Use --source export when acli is unreadable, or ask a human to run "
            "/setup-rhdh-skills jira."
            if not probe.get("readable")
            else "Jira reads are available."
        ),
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Python: {report['python']}")
        print(
            f"acli: installed={probe.get('installed')} readable={probe.get('readable')} "
            f"{probe.get('detail', '')}".rstrip()
        )
        print(f"gh: installed={bool(gh_path)}")
        print("Write path: none (dry run only)")
        print(report["nextStep"])
    return 0 if probe.get("readable") or args.allow_missing else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="triage",
        description="Read-only aged RHDHBUGS triage: select, collect, assess, report.",
    )
    parser.add_argument("--version", action="version", version="rhdh-bug-triage policy 3")
    subparsers = parser.add_subparsers(dest="command", required=True)

    progress = subparsers.add_parser(
        "progress", help="reconcile completed batch runs against a frozen inventory"
    )
    progress.add_argument("--inventory", required=True)
    progress.add_argument(
        "--run", action="append", default=[], help="completed batch run directory (repeatable)"
    )
    progress.set_defaults(func=command_progress)

    inventory = subparsers.add_parser("inventory", help="freeze a paginated, keys-only inventory")
    inventory.add_argument("--project", required=True, choices=("RHDHBUGS", "RHDHSUPP"))
    inventory.add_argument("--out", required=True)
    inventory.set_defaults(func=command_inventory)

    trigger = subparsers.add_parser(
        "trigger", help="route one delivered Jira webhook to a private work request"
    )
    trigger.add_argument("--input", required=True)
    trigger.add_argument("--out", required=True)
    trigger.set_defaults(func=command_trigger)

    event = subparsers.add_parser("event", help="consume one locally prepared, revisioned event")
    event.add_argument("--input", required=True)
    event.add_argument("--out", required=True)
    event.set_defaults(func=command_event)

    fetch_parser = subparsers.add_parser("fetch", help="download full Jira records (read-only)")
    source = fetch_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--jql")
    source.add_argument("--inventory", help="frozen all-open bug inventory")
    fetch_parser.add_argument("--batch", type=int, default=1)
    fetch_parser.add_argument("--size", type=int, default=DEFAULT_SAMPLE_SIZE)
    fetch_parser.add_argument("--out", required=True)
    fetch_parser.add_argument(
        "--field-names",
        help="JSON mapping of custom-field IDs to their names, resolved through Jira",
    )
    fetch_parser.set_defaults(func=command_fetch)

    select_parser = subparsers.add_parser(
        "select", help="pick which bugs to review, spread across teams"
    )
    select_parser.add_argument("--source", choices=("export", "acli"), default="export")
    select_parser.add_argument("--input", help="Jira JSON export")
    select_parser.add_argument(
        "--field-names", help="field-ID map for live Jira reads; exports carry their own"
    )
    select_parser.add_argument("--jql", help="JQL for acli or for the manifest record")
    select_parser.add_argument("--aged-days", type=int, default=DEFAULT_AGED_DAYS)
    select_parser.add_argument("--size", type=int, default=DEFAULT_SAMPLE_SIZE)
    select_parser.add_argument(
        "--batch", type=int, default=1, help="one-based page of the same frozen selection"
    )
    select_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    select_parser.add_argument("--current-release", required=True)
    select_parser.add_argument("--scope", choices=("aged", "all-open"), default="aged")
    select_parser.add_argument(
        "--all", action="store_true", help="review every eligible bug, not just a sample"
    )
    select_parser.add_argument(
        "--control",
        action="append",
        help="a bug with a known answer, to check us; KEY=label (repeatable)",
    )
    select_parser.add_argument("--as-of", default="", help="YYYY-MM-DD; defaults to today")
    select_parser.add_argument("--out", help="write the manifest here")
    select_parser.add_argument("--json", action="store_true")
    select_parser.set_defaults(func=command_select)

    collect_parser = subparsers.add_parser(
        "collect", help="search GitHub and Jira for leads on each picked bug"
    )
    collect_parser.add_argument("--input", required=True, help="Jira JSON export")
    collect_parser.add_argument("--sample", required=True, help="sample manifest")
    collect_parser.add_argument("--out", required=True, help="evidence directory")
    collect_parser.add_argument("--forge-cache", default="", help="offline gh PR cache")
    collect_parser.add_argument(
        "--backlog", help="the list of open and closed bugs to search for duplicates and fixes"
    )
    collect_parser.add_argument(
        "--jira-search",
        action="store_true",
        help="run the planned Jira searches too (default: only plan them)",
    )
    collect_parser.add_argument(
        "--max-queries", type=int, default=4, help="how many Jira searches to run per bug"
    )
    collect_parser.add_argument("--query-limit", type=int, default=20)
    collect_parser.add_argument(
        "--hydrate-limit",
        type=int,
        default=10,
        help="how many promising candidates to fully read per bug",
    )
    collect_parser.add_argument(
        "--field-names", help="field-ID map used when fully reading candidates"
    )
    collect_parser.add_argument(
        "--repo",
        action="append",
        help="repository to search; repeat for each repo the product uses",
    )
    collect_parser.add_argument(
        "--gh",
        action="store_true",
        help="search GitHub live with gh (default: use the local cache only)",
    )
    collect_parser.add_argument("--json", action="store_true")
    collect_parser.set_defaults(func=command_collect)

    run_parser = subparsers.add_parser(
        "run",
        help="check the assessments and write 01-triage + 02-fixes",
    )
    run_parser.add_argument("--input", required=True, help="Jira JSON export")
    run_parser.add_argument("--sample", help="sample manifest; omit to select in memory")
    run_parser.add_argument(
        "--assessments", required=True, help="directory of reviewed KEY.json assessments"
    )
    run_parser.add_argument("--out", required=True, help="output directory")
    run_parser.add_argument(
        "--current-release",
        required=True,
        help="the released product version we are checking bugs against",
    )
    run_parser.add_argument(
        "--release-evidence",
        required=True,
        help="web link that proves that version shipped (checked first)",
    )
    run_parser.add_argument("--scope", choices=("aged", "all-open"), default="aged")
    run_parser.add_argument("--all", action="store_true")
    run_parser.add_argument(
        "--evidence", help="collection directory, retained in the audit with search failures"
    )
    run_parser.add_argument(
        "--verification", help="folder of hashed source snapshots from the verify step"
    )
    run_parser.add_argument(
        "--require-investigation",
        action="store_true",
        help="refuse to run unless every check in each assessment was actually done",
    )
    run_parser.add_argument(
        "--require-fix-plan",
        action="store_true",
        help="refuse to run unless every bug has a fix plan",
    )
    run_parser.add_argument(
        "--comment-cooldown-days",
        type=int,
        default=DEFAULT_COOLDOWN_DAYS,
        help="minimum days between comments on one bug; unchanged advice is never repeated",
    )
    run_parser.add_argument("--as-of", default="")
    run_parser.add_argument("--aged-days", type=int, default=DEFAULT_AGED_DAYS)
    run_parser.add_argument("--size", type=int, default=DEFAULT_SAMPLE_SIZE)
    run_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    run_parser.add_argument("--control", action="append", help="control key, KEY=label")
    run_parser.add_argument("--backlog", help="larger export for duplicate retrieval")
    run_parser.add_argument("--jql", help="record the selection JQL in the report")
    run_parser.add_argument("--json", action="store_true")
    run_parser.set_defaults(func=command_run)

    eval_parser = subparsers.add_parser(
        "evaluate", help="score the results against bugs with known answers"
    )
    eval_parser.add_argument("--packets", required=True)
    eval_parser.add_argument("--truth", required=True)
    eval_parser.add_argument("--out", help="write the evaluation markdown here")
    eval_parser.add_argument("--strict", action="store_true")
    eval_parser.add_argument("--json", action="store_true")
    eval_parser.set_defaults(func=command_evaluate)

    verify_parser = subparsers.add_parser(
        "verify",
        help="acquire source, diff, ancestry and exact OCI metadata evidence through read-only network requests",
    )
    verify_parser.add_argument(
        "--plan",
        required=True,
        help="which sources to read and what to check, per bug",
    )
    verify_parser.add_argument(
        "--out", required=True, help="a new, empty folder for the hashed snapshots"
    )
    verify_parser.set_defaults(func=command_verify)

    template_parser = subparsers.add_parser(
        "template", help="write a fill-in file for each picked bug"
    )
    template_parser.add_argument("--sample", required=True)
    template_parser.add_argument("--out", required=True)
    template_parser.add_argument("--force", action="store_true")
    template_parser.set_defaults(func=command_template)

    brief_parser = subparsers.add_parser(
        "brief",
        help="write one self-contained file per picked bug, for its investigator",
    )
    brief_parser.add_argument("--input", required=True, help="Jira JSON export")
    brief_parser.add_argument("--sample", required=True, help="sample manifest")
    brief_parser.add_argument("--out", required=True, help="fresh brief directory")
    brief_parser.add_argument(
        "--evidence", help="collection directory with per-ticket evidence files"
    )
    brief_parser.set_defaults(func=command_brief)

    backlog_parser = subparsers.add_parser(
        "backlog",
        help="build the list of bugs to search for duplicates and fixes, in one step",
    )
    backlog_parser.add_argument(
        "--search-jql",
        action="append",
        default=[],
        help="fast partition to search (repeatable); records lack links, dates and comments",
    )
    backlog_parser.add_argument(
        "--full-jql",
        action="append",
        default=[],
        help="fully-read partition with dates, links and fix versions (repeatable)",
    )
    backlog_parser.add_argument("--out", required=True, help="fresh backlog export path")
    backlog_parser.add_argument(
        "--field-names",
        help="JSON mapping of custom-field IDs to their names, resolved through Jira",
    )
    backlog_parser.set_defaults(func=command_backlog)

    check_parser = subparsers.add_parser(
        "check", help="show what this tool can reach, without writing anything"
    )
    check_parser.add_argument("--json", action="store_true")
    check_parser.add_argument("--allow-missing", action="store_true")
    check_parser.set_defaults(func=command_check)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RunError, JiraAdapterError, ForgeAdapterError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
