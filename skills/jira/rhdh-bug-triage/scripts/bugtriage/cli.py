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
from pathlib import Path
from typing import List, Optional

from .collect import CollectConfig, collect
from .evaluate import write_evaluation
from .forge import ForgeAdapterError
from .jira import JiraAdapterError, load_tickets_from_acli, write_acli_probe
from .model import (
    DEFAULT_AGED_DAYS,
    DEFAULT_CURRENT_RELEASE,
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_SEED,
    load_export,
)
from .report import write_json
from .run import (
    RunConfig,
    RunError,
    build_sample_manifest,
    default_jql,
    parse_as_of,
    run,
)
from .selection import Control, SelectionConfig


def _controls(values: Optional[List[str]]) -> List[Control]:
    controls = []
    for value in values or []:
        key, _, label = value.partition("=")
        if key.strip():
            controls.append(Control(key=key.strip(), label=label.strip()))
    return controls


def _load_tickets(args: argparse.Namespace):
    if args.source == "acli":
        return load_tickets_from_acli(args.jql or default_jql(args.aged_days))
    if not args.input:
        raise RunError("--input is required when --source=export")
    return load_export(args.input)


def command_select(args: argparse.Namespace) -> int:
    as_of = parse_as_of(args.as_of)
    tickets = _load_tickets(args)
    jql = args.jql or default_jql(args.aged_days)
    config = SelectionConfig(
        size=args.size,
        aged_days=args.aged_days,
        seed=args.seed,
        controls=_controls(args.control),
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
        "dispositions": _count(result.packets, "disposition"),
        "actions": _count(result.packets, "action"),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        actionable = sum(1 for packet in result.packets if packet.action != "unclear")
        close = [packet for packet in result.packets if packet.action.startswith("propose_close")]
        print(f"DRY RUN complete: {counts['packets']} ticket(s) in {result.output_dir}")
        print("Nothing was posted, transitioned, linked, or written to Jira.")
        print("")
        if close:
            print(f"{len(close)} close proposal(s) need your review:")
            for packet in close:
                print(f"  {packet.key}  {packet.disposition}  {packet.recommended_step}")
        else:
            print("No close proposals. Nothing is waiting for a close decision.")
        print("")
        print(
            f"Ready to review: {actionable}/{counts['packets']} · "
            f"cited evidence: {counts['withEvidence']}/{counts['packets']} · "
            f"customer-linked: {counts['customerLinked']}"
        )
        print(
            "Read report.md for the per-ticket table; the exact comment for each "
            "ticket is in proposed/KEY.md."
        )
    return 0


def _count(packets, attribute: str) -> dict:
    counts: dict = {}
    for packet in packets:
        value = getattr(packet, attribute)
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


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
        hard_fail = bool(evaluation.false_closes) or evaluation.decision_ready_rate < 0.8
        return 1 if hard_fail else 0
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
                    "Fill disposition and evidence. Every evidence item needs type, ref, "
                    "why, and strength (direct|strong|supporting). Do not invent a "
                    "confidence; the policy computes it. A close also needs two agreeing "
                    "independent passes under review."
                ),
                "disposition": "",
                "duplicateOf": "",
                "evidence": [],
                "fix": {"pr": "", "commit": "", "release": "", "released": False},
                "repro": {"result": "not_run", "release": "", "notes": ""},
                "review": {"independentPasses": 0, "agree": False},
                "notes": "",
                "comment": "",
            },
        )
        written.append(key)
    print(f"Wrote {len(written)} assessment template(s) to {output}")
    if skipped:
        print(f"Skipped {len(skipped)} existing file(s); pass --force to overwrite")
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
        prog="run_poc",
        description="Read-only aged RHDHBUGS triage: select, collect, assess, report.",
    )
    parser.add_argument("--version", action="version", version="rhdh-bug-triage 1")
    subparsers = parser.add_subparsers(dest="command", required=True)

    select_parser = subparsers.add_parser("select", help="build a stratified sample manifest")
    select_parser.add_argument("--source", choices=("export", "acli"), default="export")
    select_parser.add_argument("--input", help="Jira JSON export")
    select_parser.add_argument("--jql", help="JQL for acli or for the manifest record")
    select_parser.add_argument("--aged-days", type=int, default=DEFAULT_AGED_DAYS)
    select_parser.add_argument("--size", type=int, default=DEFAULT_SAMPLE_SIZE)
    select_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
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
    run_parser.add_argument("--assessments", help="directory of KEY.json assessments")
    run_parser.add_argument("--out", required=True, help="output directory")
    run_parser.add_argument("--current-release", default=DEFAULT_CURRENT_RELEASE)
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

    template_parser = subparsers.add_parser(
        "template", help="write assessment templates for a sample"
    )
    template_parser.add_argument("--sample", required=True)
    template_parser.add_argument("--out", required=True)
    template_parser.add_argument("--force", action="store_true")
    template_parser.set_defaults(func=command_template)

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
