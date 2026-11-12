"""Orchestration for one dry-run triage pass.

The pipeline is intentionally offline and deterministic: selection, retrieval,
assessment loading, policy, verification, and rendering. The only optional
network step is GitHub PR enrichment in ``collect``; ``run`` reads its cache.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .duplicates import (
    DUPLICATE_CLOSE_THRESHOLD,
    DUPLICATE_HINT_THRESHOLD,
    rank_candidates,
)
from .model import (
    DEFAULT_CURRENT_RELEASE,
    Ticket,
    age_days,
    load_export,
    parse_datetime,
)
from .policy import (
    FIXED_CLOSE_THRESHOLD,
    OBSOLETE_CLOSE_THRESHOLD,
    POLICY_VERSION,
    Assessment,
    Packet,
    evaluate,
    load_assessment,
    verify_packet,
)
from .report import (
    now_iso,
    render_manifest,
    render_packet,
    render_report,
    render_summary_csv,
    write_json,
    write_text,
)
from .selection import Control, SelectionConfig, select_sample


class RunError(RuntimeError):
    """The run cannot produce a trustworthy report."""


@dataclass
class RunConfig:
    input_path: str
    output_dir: str
    sample_path: str = ""
    assessments_dir: str = ""
    current_release: str = DEFAULT_CURRENT_RELEASE
    as_of: str = ""
    aged_days: int = 90
    size: int = 12
    seed: int = 18094
    controls: List[Control] = field(default_factory=list)
    corpus_path: str = ""
    jql: str = ""


@dataclass
class RunResult:
    packets: List[Packet]
    tickets: Dict[str, Ticket]
    sample: Dict[str, Any]
    manifest: Dict[str, Any]
    output_dir: Path


def default_jql(aged_days: int) -> str:
    return (
        "project = RHDHBUGS AND statusCategory != Done "
        f'AND created <= -{aged_days}d AND labels != "RHDH-Customer" '
        "ORDER BY created ASC"
    )


def parse_as_of(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = parse_datetime(value)
    if parsed is None:
        raise RunError(f"cannot parse --as-of {value!r}; use YYYY-MM-DD")
    return parsed


def build_sample_manifest(
    tickets: Iterable[Ticket],
    config: SelectionConfig,
    as_of: datetime,
    jql: str,
) -> Dict[str, Any]:
    selected, excluded, eligible_count = select_sample(tickets, config, as_of)
    return {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "asOf": as_of.date().isoformat(),
        "jql": jql,
        "agedDays": config.aged_days,
        "size": config.size,
        "seed": config.seed,
        "controls": [{"key": control.key, "label": control.label} for control in config.controls],
        "eligibleCount": eligible_count,
        "tickets": [item.manifest_entry() for item in selected],
        "excluded": excluded,
    }


def load_sample_manifest(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict) or not isinstance(document.get("tickets"), list):
        raise RunError(f"{path} is not a sample manifest with a tickets list")
    return document


def data_gaps(ticket: Ticket) -> List[str]:
    gaps: List[str] = []
    if not ticket.affects_versions:
        gaps.append("affects version absent from the export")
    if not ticket.fix_versions:
        gaps.append("fix version absent from the export")
    if not ticket.description.strip():
        gaps.append("description empty or absent from the export")
    if not ticket.comments:
        gaps.append("no comments present in the export")
    if not ticket.links:
        gaps.append("no Jira links present in the export")
    if ticket.created and age_days(ticket.created) is None:
        gaps.append("created date unreadable")
    return gaps


def load_assessments(directory: str) -> Dict[str, Assessment]:
    root = Path(directory)
    if not directory or not root.is_dir():
        return {}
    assessments: Dict[str, Assessment] = {}
    for path in sorted(root.glob("*.json")):
        try:
            assessment = load_assessment(str(path))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RunError(f"invalid assessment {path}: {error}") from error
        assessments[assessment.key] = assessment
    return assessments


def run(config: RunConfig) -> RunResult:
    as_of = parse_as_of(config.as_of)
    tickets = load_export(config.input_path)
    if not tickets:
        raise RunError(f"{config.input_path} contains no issues")
    tickets_by_key = {ticket.key: ticket for ticket in tickets}
    jql = config.jql or default_jql(config.aged_days)

    if config.sample_path:
        sample = load_sample_manifest(config.sample_path)
    else:
        selection_config = SelectionConfig(
            size=config.size,
            aged_days=config.aged_days,
            seed=config.seed,
            controls=config.controls,
        )
        sample = build_sample_manifest(tickets, selection_config, as_of, jql)

    selection = {entry["key"]: entry for entry in sample.get("tickets", [])}
    if not selection:
        raise RunError("the sample manifest is empty; select tickets before running")

    missing = sorted(key for key in selection if key not in tickets_by_key)
    if missing:
        raise RunError("the sample names tickets missing from the export: " + ", ".join(missing))

    corpus = tickets
    if config.corpus_path:
        corpus = load_export(config.corpus_path)
    # Duplicate retrieval is only as good as the corpus. A closed canonical
    # report is invisible when the export holds open tickets only, so record
    # that instead of silently implying the search was complete.
    corpus_has_closed = any(ticket.is_done for ticket in corpus)

    assessments = load_assessments(config.assessments_dir)
    packets: List[Packet] = []
    for key in selection:
        ticket = tickets_by_key[key]
        candidates = rank_candidates(ticket, corpus, limit=3)
        packet = evaluate(
            ticket,
            candidates,
            assessments.get(key),
            current_release=config.current_release,
        )
        for gap in data_gaps(ticket):
            if gap not in packet.gaps:
                packet.gaps.append(gap)
        packet.verification_errors = verify_packet(packet, ticket)
        if packet.verification_errors and packet.action in (
            "propose_close_duplicate",
            "propose_close_fixed",
            "propose_close_obsolete",
        ):
            packet.action = "comment_only"
            packet.recommended_step = (
                "Verifier rejected the close proposal; keep open and review the evidence."
            )
        packets.append(packet)

    generated_at = now_iso()
    output_dir = Path(config.output_dir)
    proposals_dir = output_dir / "proposed"
    thresholds = {
        "duplicate": DUPLICATE_CLOSE_THRESHOLD,
        "duplicateHint": DUPLICATE_HINT_THRESHOLD,
        "fixed": FIXED_CLOSE_THRESHOLD,
        "obsolete": OBSOLETE_CLOSE_THRESHOLD,
    }

    report = render_report(
        packets,
        tickets_by_key,
        generated_at=generated_at,
        as_of=as_of,
        current_release=config.current_release,
        jql=jql,
        sample_size=sum(1 for entry in selection.values() if entry.get("kind") == "aged"),
        control_count=sum(1 for entry in selection.values() if entry.get("kind") == "control"),
        corpus_size=len(corpus),
        corpus_has_closed=corpus_has_closed,
        excluded=sample.get("excluded", []),
        selection=selection,
        thresholds=thresholds,
    )
    write_text(output_dir / "report.md", report)
    write_text(output_dir / "summary.csv", render_summary_csv(packets, selection))
    write_json(
        output_dir / "packets.json",
        {
            "schemaVersion": 1,
            "dryRun": True,
            "generatedAt": generated_at,
            "currentRelease": config.current_release,
            "packets": [packet.to_dict() for packet in packets],
        },
    )
    for packet in packets:
        ticket = tickets_by_key[packet.key]
        entry = selection.get(packet.key, {})
        write_text(
            proposals_dir / f"{packet.key}.md",
            render_packet(
                packet,
                ticket,
                kind=str(entry.get("kind", "aged")),
                stratum=str(entry.get("stratum", "")),
                control_label=str(entry.get("controlLabel", "")),
                as_of=as_of,
                generated_at=generated_at,
            ),
        )

    manifest = render_manifest(
        generated_at=generated_at,
        as_of=as_of,
        current_release=config.current_release,
        jql=jql,
        input_path=config.input_path,
        sample_path=config.sample_path or "(selected in memory)",
        assessments_path=config.assessments_dir or "(none)",
        output_path=str(output_dir),
        corpus_size=len(corpus),
        corpus_has_closed=corpus_has_closed,
        sample_size=sum(1 for entry in selection.values() if entry.get("kind") == "aged"),
        control_count=sum(1 for entry in selection.values() if entry.get("kind") == "control"),
        packets=packets,
        thresholds=thresholds,
        policy_version=POLICY_VERSION,
    )
    write_json(output_dir / "manifest.json", manifest)

    return RunResult(
        packets=packets,
        tickets=tickets_by_key,
        sample=sample,
        manifest=manifest,
        output_dir=output_dir,
    )
