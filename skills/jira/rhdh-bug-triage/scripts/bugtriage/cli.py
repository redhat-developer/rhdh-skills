"""Command-line surface for the RHDH aged-bug triage skill.

Every command is read-only. ``run`` refuses to accept an apply flag because no
write path exists; proposed actions are files under the output directory.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import List, Optional

from .collect import CollectConfig, collect
from .comments import DEFAULT_COOLDOWN_DAYS
from .dossier import write_dossiers
from .evaluate import write_evaluation
from .forge import ForgeAdapterError
from .jira import (
    JiraAdapterError,
    build_corpus,
    export_from_acli,
    load_tickets_from_acli,
    write_acli_probe,
)
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
    if (
        not isinstance(document, dict)
        or not document
        or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in document.items())
    ):
        raise RunError("--field-names must contain the tenant-resolved field-ID to name mapping")
    return document


def command_fetch(args: argparse.Namespace) -> int:
    path = Path(args.out)
    if path.exists():
        raise RunError(f"refusing to overwrite export: {path}")
    document = export_from_acli(args.jql, field_names=_field_names(args.field_names))
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
    sample = build_sample_manifest(tickets, config, as_of, jql)
    if args.out:
        write_json(Path(args.out), sample)
    if args.json:
        print(json.dumps(sample, indent=2))
    else:
        print(
            f"Selected {len(sample['tickets'])} ticket(s) from "
            f"{sample['eligibleCount']} eligible in a corpus of {len(tickets)}."
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
            corpus_path=args.corpus or "",
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
            corpus_path=args.corpus or "",
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
        "dispositions": _count(result.packets, "disposition"),
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
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"DRY RUN complete: {counts['packets']} ticket(s) in {result.output_dir}")
        print("Nothing was posted to Jira; no bugs were closed and no PRs were created.")
        for packet in result.packets:
            print(
                f"  {packet.key}  {packet.disposition}  delivery={packet.comment_plan.get('status', 'unknown')}"
            )
        print(
            f"Draft comments: {counts['draftComments']} · advisory closure recommendations: {counts['closeProposals']}"
        )
        print(f"Comment delivery: {result.manifest['commentPolicy']['counts']}")
        print(
            "Read report.md (the only human-facing file); packets, manifest and "
            "machine artifacts are under audit/."
        )
    return 0


def _count(packets, attribute: str) -> dict:
    counts: dict = {}
    for packet in packets:
        value = getattr(packet, attribute)
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def command_dossier(args: argparse.Namespace) -> int:
    written = write_dossiers(
        input_path=args.input,
        sample_path=args.sample,
        output_dir=args.out,
        evidence_dir=args.evidence or "",
    )
    print(f"Wrote {len(written)} investigator dossier(s) into {args.out}")
    print("Give one dossier per fresh-context investigator; each writes assessments/KEY.json.")
    return 0


def command_corpus(args: argparse.Namespace) -> int:
    if not args.search_jql and not args.full_jql:
        raise RunError("corpus needs at least one --search-jql or --full-jql part")
    path = Path(args.out)
    if path.exists():
        raise RunError(f"refusing to overwrite corpus: {path}")
    document = build_corpus(
        search_jqls=list(args.search_jql or []),
        full_jqls=list(args.full_jql or []),
        field_names=_field_names(args.field_names),
        as_of=now_iso(),
    )
    write_json(path, document)
    parts = document["provenance"]["parts"]
    print(f"Built a {len(document['issues'])}-record corpus from {len(parts)} part(s) into {path}")
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
                    "Triage every selected issue. Unknown is a result, not silence. "
                    "Still-valid/obsolete require validation on the exact release under review. "
                    "Every evidence item needs type, ref, "
                    "why, and strength (direct|strong|supporting). Do not invent a "
                    "confidence; the policy computes it. A close also needs two agreeing "
                    "independent passes under review. Every investigated bug needs a "
                    "fixPlan: the concrete read-only remediation approach (or the "
                    "resolution action for duplicate/already-fixed/obsolete), the areas "
                    "a fix would touch, and a complexity estimate."
                ),
                "disposition": "",
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

    fetch_parser = subparsers.add_parser(
        "fetch", help="export full Jira records using read-only authenticated reads"
    )
    fetch_parser.add_argument("--jql", required=True)
    fetch_parser.add_argument("--out", required=True)
    fetch_parser.add_argument(
        "--field-names",
        help="JSON field-ID to name mapping returned by the authenticated Jira adapter",
    )
    fetch_parser.set_defaults(func=command_fetch)

    select_parser = subparsers.add_parser("select", help="build a stratified sample manifest")
    select_parser.add_argument("--source", choices=("export", "acli"), default="export")
    select_parser.add_argument("--input", help="Jira JSON export")
    select_parser.add_argument(
        "--field-names", help="tenant field-ID map for live acli reads; exports carry fieldNames"
    )
    select_parser.add_argument("--jql", help="JQL for acli or for the manifest record")
    select_parser.add_argument("--aged-days", type=int, default=DEFAULT_AGED_DAYS)
    select_parser.add_argument("--size", type=int, default=DEFAULT_SAMPLE_SIZE)
    select_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    select_parser.add_argument("--current-release", required=True)
    select_parser.add_argument("--scope", choices=("aged", "all-open"), default="aged")
    select_parser.add_argument(
        "--all", action="store_true", help="select every eligible issue, not a sample"
    )
    select_parser.add_argument(
        "--control",
        action="append",
        help="control key, optionally KEY=label (repeatable)",
    )
    select_parser.add_argument("--as-of", default="", help="YYYY-MM-DD; defaults to today")
    select_parser.add_argument("--out", help="write the manifest here")
    select_parser.add_argument("--json", action="store_true")
    select_parser.set_defaults(func=command_select)

    collect_parser = subparsers.add_parser("collect", help="collect PR and link evidence")
    collect_parser.add_argument("--input", required=True, help="Jira JSON export")
    collect_parser.add_argument("--sample", required=True, help="sample manifest")
    collect_parser.add_argument("--out", required=True, help="evidence directory")
    collect_parser.add_argument("--forge-cache", default="", help="offline gh PR cache")
    collect_parser.add_argument("--corpus", help="bounded open-and-closed candidate export")
    collect_parser.add_argument(
        "--jira-search",
        action="store_true",
        help="execute separate defect-card JQL reads (default: plans only)",
    )
    collect_parser.add_argument(
        "--max-queries", type=int, default=4, help="live query budget per issue"
    )
    collect_parser.add_argument("--query-limit", type=int, default=20)
    collect_parser.add_argument(
        "--hydrate-limit", type=int, default=10, help="new full candidate reads per issue"
    )
    collect_parser.add_argument(
        "--field-names", help="tenant field-ID mapping for candidate full reads"
    )
    collect_parser.add_argument(
        "--repo",
        action="append",
        help="repository to search; repeat for the resolved product, docs and plugin repositories",
    )
    collect_parser.add_argument(
        "--gh",
        action="store_true",
        help="allow read-only gh calls for PR state (default: cache only)",
    )
    collect_parser.add_argument("--json", action="store_true")
    collect_parser.set_defaults(func=command_collect)

    run_parser = subparsers.add_parser("run", help="evaluate assessments and render a report")
    run_parser.add_argument("--input", required=True, help="Jira JSON export")
    run_parser.add_argument("--sample", help="sample manifest; omit to select in memory")
    run_parser.add_argument(
        "--assessments", required=True, help="directory of reviewed KEY.json assessments"
    )
    run_parser.add_argument("--out", required=True, help="output directory")
    run_parser.add_argument(
        "--current-release", required=True, help="verified released product version under review"
    )
    run_parser.add_argument(
        "--release-evidence",
        required=True,
        help="HTTPS product release record (verified by the agent)",
    )
    run_parser.add_argument("--scope", choices=("aged", "all-open"), default="aged")
    run_parser.add_argument("--all", action="store_true")
    run_parser.add_argument(
        "--evidence", help="collection directory, retained in the audit with search failures"
    )
    run_parser.add_argument(
        "--verification", help="integrity-checked source/release/artifact receipt directory"
    )
    run_parser.add_argument(
        "--require-investigation",
        action="store_true",
        help="reject placeholder/absent or invalid per-requirement investigations",
    )
    run_parser.add_argument(
        "--require-fix-plan",
        action="store_true",
        help="reject assessments without concrete read-only fix guidance (fixPlan)",
    )
    run_parser.add_argument(
        "--comment-cooldown-days",
        type=int,
        default=DEFAULT_COOLDOWN_DAYS,
        help="minimum days between triage comments; pending/unchanged recommendations still suppress",
    )
    run_parser.add_argument("--as-of", default="")
    run_parser.add_argument("--aged-days", type=int, default=DEFAULT_AGED_DAYS)
    run_parser.add_argument("--size", type=int, default=DEFAULT_SAMPLE_SIZE)
    run_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    run_parser.add_argument("--control", action="append", help="control key, KEY=label")
    run_parser.add_argument("--corpus", help="larger export for duplicate retrieval")
    run_parser.add_argument("--jql", help="record the selection JQL in the report")
    run_parser.add_argument("--json", action="store_true")
    run_parser.set_defaults(func=command_run)

    eval_parser = subparsers.add_parser("evaluate", help="score packets against ground truth")
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
        help="explicit per-issue requirements and source/artifact read plan",
    )
    verify_parser.add_argument("--out", required=True, help="fresh private verification directory")
    verify_parser.set_defaults(func=command_verify)

    template_parser = subparsers.add_parser(
        "template", help="write assessment templates for a sample"
    )
    template_parser.add_argument("--sample", required=True)
    template_parser.add_argument("--out", required=True)
    template_parser.add_argument("--force", action="store_true")
    template_parser.set_defaults(func=command_template)

    dossier_parser = subparsers.add_parser(
        "dossier",
        help="write one self-contained investigator file per sampled ticket",
    )
    dossier_parser.add_argument("--input", required=True, help="Jira JSON export")
    dossier_parser.add_argument("--sample", required=True, help="sample manifest")
    dossier_parser.add_argument("--out", required=True, help="fresh dossier directory")
    dossier_parser.add_argument(
        "--evidence", help="collection directory with per-ticket evidence files"
    )
    dossier_parser.set_defaults(func=command_dossier)

    corpus_parser = subparsers.add_parser(
        "corpus",
        help="build one merged open-and-closed candidate corpus from bounded parts",
    )
    corpus_parser.add_argument(
        "--search-jql",
        action="append",
        default=[],
        help="fast search-level partition (repeatable); records lack links, dates and comments",
    )
    corpus_parser.add_argument(
        "--full-jql",
        action="append",
        default=[],
        help="full-read partition with chronology, links and fix versions (repeatable)",
    )
    corpus_parser.add_argument("--out", required=True, help="fresh corpus export path")
    corpus_parser.add_argument(
        "--field-names",
        help="JSON field-ID to name mapping returned by the authenticated Jira adapter",
    )
    corpus_parser.set_defaults(func=command_corpus)

    check_parser = subparsers.add_parser("check", help="report capability without writing")
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
