"""Orchestration for one dry-run triage pass.

The pipeline is intentionally offline and deterministic: selection, retrieval,
assessment loading, policy, verification, and rendering. The only optional
network step is GitHub PR enrichment in ``collect``; ``run`` reads its cache.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .comments import DEFAULT_COOLDOWN_DAYS, attach_comment_plan
from .discovery import discover
from .duplicates import (
    DUPLICATE_CLOSE_THRESHOLD,
    DUPLICATE_HINT_THRESHOLD,
    rank_candidates,
    score_candidate,
)
from .layout import write_phased_output
from .model import (
    JIRA_KEY_RE,
    Ticket,
    age_days,
    load_export,
    normalize_issue,
    parse_datetime,
)
from .policy import (
    FIXED_CLOSE_THRESHOLD,
    POLICY_VERSION,
    Assessment,
    Packet,
    evaluate,
    investigation_errors,
    load_assessment,
    recommendation_comment,
)
from .report import now_iso, render_manifest
from .selection import Control, SelectionConfig, select_sample
from .verification import load_verification


class RunError(RuntimeError):
    """The run cannot produce a trustworthy report."""


@dataclass
class RunConfig:
    input_path: str
    output_dir: str
    current_release: str
    sample_path: str = ""
    assessments_dir: str = ""
    as_of: str = ""
    aged_days: int = 90
    size: int = 12
    seed: int = 18094
    controls: List[Control] = field(default_factory=list)
    backlog_path: str = ""
    jql: str = ""
    comment_cooldown_days: int = DEFAULT_COOLDOWN_DAYS
    scope: str = "aged"
    all_tickets: bool = False
    release_evidence: str = ""
    evidence_dir: str = ""
    verification_dir: str = ""
    require_investigation: bool = False
    require_fix_plan: bool = False


@dataclass
class RunResult:
    packets: List[Packet]
    tickets: Dict[str, Ticket]
    sample: Dict[str, Any]
    manifest: Dict[str, Any]
    output_dir: Path


def default_jql(aged_days: int, scope: str = "aged") -> str:
    return (
        "project = RHDHBUGS AND statusCategory != Done "
        + (f"AND created <= -{aged_days}d " if scope == "aged" else "")
        + 'AND (labels IS EMPTY OR labels NOT IN ("RHDH-Customer")) '
        + "ORDER BY created ASC"
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
        "schemaVersion": 3,
        "generatedAt": now_iso(),
        "asOf": as_of.date().isoformat(),
        "jql": jql,
        "agedDays": config.aged_days,
        "size": config.size,
        "seed": config.seed,
        "scope": config.scope,
        "currentRelease": config.current_release,
        "allTickets": config.all_tickets,
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
    keys = []
    for entry in document["tickets"]:
        key = entry.get("key") if isinstance(entry, dict) else None
        if not isinstance(key, str) or not JIRA_KEY_RE.fullmatch(key):
            raise RunError(f"{path} contains an invalid issue key")
        keys.append(key)
    if len(keys) != len(set(keys)):
        raise RunError(f"{path} contains duplicate issue keys")
    return document


def data_gaps(ticket: Ticket) -> List[str]:
    gaps: List[str] = list(ticket.read_gaps)
    if not ticket.affects_versions:
        gaps.append("affects version absent from the export")
    if not ticket.description.strip():
        gaps.append("description empty or absent from the export")
    if not ticket.comments_complete:
        gaps.append("comment history is incomplete or was not fetched")
    if ticket.created and age_days(ticket.created) is None:
        gaps.append("created date unreadable")
    return gaps


def load_assessments(directory: str) -> Dict[str, Assessment]:
    root = Path(directory)
    if not directory or not root.is_dir():
        raise RunError(f"assessment directory does not exist: {directory!r}")
    assessments: Dict[str, Assessment] = {}
    for path in sorted(root.glob("*.json")):
        try:
            assessment = load_assessment(str(path))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RunError(f"invalid assessment {path}: {error}") from error
        if path.stem != assessment.key:
            raise RunError(f"assessment {path} names a different issue: {assessment.key}")
        if not assessment.verdict:
            raise RunError(
                f"assessment {path} is still an unfilled template; investigate before running"
            )
        assessments[assessment.key] = assessment
    return assessments


def run(config: RunConfig) -> RunResult:
    if config.comment_cooldown_days < 0:
        raise RunError("--comment-cooldown-days must be nonnegative")
    output_dir = Path(config.output_dir)
    if output_dir.exists():
        raise RunError(
            "output directory already exists; use a fresh directory to avoid stale proposals"
        )
    from .policy import valid_ref

    if (
        not config.release_evidence
        or not config.release_evidence.startswith("https://")
        or not valid_ref(config.release_evidence)
    ):
        raise RunError("--release-evidence must link the verified product release record")
    as_of = parse_as_of(config.as_of)
    tickets = load_export(config.input_path)
    if not tickets:
        raise RunError(f"{config.input_path} contains no issues")
    tickets_by_key = {ticket.key: ticket for ticket in tickets}
    jql = config.jql or default_jql(config.aged_days, config.scope)

    if config.sample_path:
        sample = load_sample_manifest(config.sample_path)
        if (
            sample.get("currentRelease") != config.current_release
            or sample.get("scope") != config.scope
        ):
            raise RunError("sample release/scope does not match this run; select again")
    else:
        selection_config = SelectionConfig(
            size=config.size,
            aged_days=config.aged_days,
            seed=config.seed,
            controls=config.controls,
            current_release=config.current_release,
            scope=config.scope,
            all_tickets=config.all_tickets,
        )
        sample = build_sample_manifest(tickets, selection_config, as_of, jql)

    selection = {entry["key"]: entry for entry in sample.get("tickets", [])}

    missing = sorted(key for key in selection if key not in tickets_by_key)
    if missing:
        raise RunError("the sample names tickets missing from the export: " + ", ".join(missing))

    # Eligibility changes with time and incoming records even when every selected
    # key is still present. An old zero-item manifest must not hide the backlog.
    if sample.get("agedDays", config.aged_days) != config.aged_days:
        raise RunError("sample age threshold does not match this run; select again")
    _, current_exclusions, current_eligible = select_sample(
        tickets,
        SelectionConfig(
            size=config.size,
            aged_days=config.aged_days,
            seed=config.seed,
            current_release=config.current_release,
            scope=config.scope,
            controls=[
                Control(key=entry["key"], label=entry.get("label", ""))
                for entry in sample.get("controls", [])
            ],
        ),
        as_of,
    )
    if sample.get("eligibleCount") != current_eligible:
        raise RunError(
            "sample eligibility count is stale; select again against the current inventory/date"
        )
    sample["excluded"] = current_exclusions

    # A supplied manifest is not permission to bypass current eligibility.
    from .selection import exclusion_reason

    for key, entry in selection.items():
        ticket = tickets_by_key[key]
        if entry.get("kind") == "control":
            continue
        reason = exclusion_reason(
            ticket, as_of, config.aged_days, config.current_release, config.scope
        )
        if reason:
            raise RunError(f"sample issue {key} is no longer eligible: {reason}")

    backlog = tickets
    if config.backlog_path:
        backlog = load_export(config.backlog_path)
    assessments = load_assessments(config.assessments_dir)
    absent = sorted(set(selection) - set(assessments))
    if absent:
        raise RunError("missing assessments (triage has not completed): " + ", ".join(absent))
    if config.require_investigation:
        for key in selection:
            assessment = assessments[key]
            errors = investigation_errors(
                assessment.investigation, assessment.evidence, config.current_release
            )
            if errors:
                raise RunError(f"investigation incomplete for {key}: " + "; ".join(errors))
    if config.require_fix_plan:
        from .policy import fix_plan_errors

        for key in selection:
            assessment = assessments[key]
            errors = fix_plan_errors(assessment.fix_plan, assessment.evidence, assessment.verdict)
            if errors:
                raise RunError(f"fix plan incomplete for {key}: " + "; ".join(errors))
    collection = {}
    if config.evidence_dir:
        evidence_root = Path(config.evidence_dir)
        if not evidence_root.is_dir():
            raise RunError(f"evidence directory does not exist: {config.evidence_dir}")
        for key in selection:
            path = evidence_root / f"{key}.json"
            if not path.is_file():
                raise RunError(f"missing collection evidence: {path}")
            collection[key] = json.loads(path.read_text(encoding="utf-8"))
    verification = (
        load_verification(config.verification_dir, selection, config.current_release)
        if config.verification_dir
        else {}
    )
    backlog_by_key = {item.key: item for item in backlog}
    for key, evidence in collection.items():
        discovery = evidence.get("discovery", {})
        if discovery and discovery.get("key") != key:
            raise RunError(f"discovery evidence does not match {key}")
        for record in discovery.get("candidateRecords", []):
            candidate = normalize_issue(record)
            # Fresh collected records supersede the bounded backlog snapshot.
            backlog_by_key[candidate.key] = candidate
    backlog_by_key.update(tickets_by_key)
    backlog = list(backlog_by_key.values())
    # Duplicate retrieval is only as good as the backlog. A closed canonical
    # report is invisible when the export holds open tickets only, so record
    # that instead of silently implying the search was complete.
    backlog_has_closed = any(item.is_done for item in backlog)
    packets: List[Packet] = []
    for key in selection:
        ticket = tickets_by_key[key]
        candidates = rank_candidates(ticket, backlog, limit=10)
        discovery = discover(ticket, backlog)
        collected_discovery = collection.get(key, {}).get("discovery", {})
        if collected_discovery:
            discovery["collection"] = collected_discovery
            by_lead = {lead["key"]: lead for lead in discovery["leads"]}
            for lead in collected_discovery.get("leads", []):
                if lead["key"] not in by_lead:
                    by_lead[lead["key"]] = lead
                    continue
                current = by_lead[lead["key"]]
                for field in ("foundBy", "reasons", "warnings"):
                    for value in lead.get(field, []):
                        if value not in current.setdefault(field, []):
                            current[field].append(value)
            discovery["leads"] = [by_lead[key] for key in sorted(by_lead)]
        discovered_keys = {lead["key"] for lead in discovery["leads"]}
        discovered_keys.update(lead["key"] for lead in collected_discovery.get("leads", []))
        for candidate_key in sorted(discovered_keys):
            if candidate_key in backlog_by_key and all(c.key != candidate_key for c in candidates):
                candidates.append(score_candidate(ticket, backlog_by_key[candidate_key]))
        assessment = assessments.get(key)
        # An explicitly investigated target may lie outside the top lexical hits.
        if (
            assessment
            and assessment.duplicate_of in backlog_by_key
            and all(c.key != assessment.duplicate_of for c in candidates)
        ):
            candidates.append(score_candidate(ticket, backlog_by_key[assessment.duplicate_of]))
        packet = evaluate(
            ticket,
            candidates,
            assessment,
            current_release=config.current_release,
            verification=verification.get(key),
        )
        packet.discovery = discovery
        for gap in data_gaps(ticket):
            if gap not in packet.gaps:
                packet.gaps.append(gap)
        attach_comment_plan(
            ticket, packet, assessments.get(key), as_of, config.comment_cooldown_days
        )
        packets.append(packet)

    redundant = {packet.key for packet in packets if packet.action == "propose_close_duplicate"}
    for packet in packets:
        if packet.action == "propose_close_duplicate" and packet.target in redundant:
            packet.action, packet.verdict = "comment_only", "unclear"
            packet.recommended_step = (
                "Resolve the duplicate chain to one canonical tracker before recommending closure."
            )
            packet.gaps.append(
                "canonical tracker is also proposed as a duplicate; re-adjudicate against the final tracker"
            )
            packet.proposed_comment = recommendation_comment(packet, tickets_by_key[packet.key])
            attach_comment_plan(
                tickets_by_key[packet.key],
                packet,
                assessments.get(packet.key),
                as_of,
                config.comment_cooldown_days,
            )

    generated_at = now_iso()
    thresholds = {
        "duplicate": DUPLICATE_CLOSE_THRESHOLD,
        "duplicateHint": DUPLICATE_HINT_THRESHOLD,
        "fixed": FIXED_CLOSE_THRESHOLD,
    }

    coverage = {
        "inputIssues": len(tickets),
        "eligibleIssues": sample.get("eligibleCount", 0),
        "selectedIssues": len(selection),
        "assessedIssues": len(packets),
        "excludedIssues": len(sample.get("excluded", [])),
        "scope": config.scope,
        "selectionComplete": len(selection) >= sample.get("eligibleCount", 0),
        "corpusIssues": len(backlog),
        "corpusHasClosed": backlog_has_closed,
        "corpusExhaustive": False,
        "collection": collection,
    }
    # The run root holds two phases: 01-triage (decide, comment, prove) and
    # 02-fixes (a handoff scaffold for separately approved write work).
    # Working inputs stay outside this directory.
    output_dir.mkdir(parents=True, exist_ok=False)

    meta = render_manifest(
        generated_at=generated_at,
        as_of=as_of,
        current_release=config.current_release,
        jql=jql,
        input_path=config.input_path,
        sample_path=config.sample_path or "(selected in memory)",
        assessments_path=config.assessments_dir or "(none)",
        output_path=str(output_dir),
        backlog_size=len(backlog),
        backlog_has_closed=backlog_has_closed,
        sample_size=sum(1 for entry in selection.values() if entry.get("kind") != "control"),
        control_count=sum(1 for entry in selection.values() if entry.get("kind") == "control"),
        packets=packets,
        thresholds=thresholds,
        policy_version=POLICY_VERSION,
    )
    meta["commentPolicy"] = {
        "cooldownDays": config.comment_cooldown_days,
        "historySource": "complete Jira comments; dry runs are not posting history",
        "counts": {
            status: sum(packet.comment_plan.get("status") == status for packet in packets)
            for status in ("propose", "suppress", "review_required")
        },
    }
    meta["releaseEvidence"] = config.release_evidence
    meta["investigationRequired"] = config.require_investigation
    meta["fixPlanRequired"] = config.require_fix_plan
    meta["investigationStates"] = {
        status: sum(p.investigation.get("status", "not_recorded") == status for p in packets)
        for status in ("completed", "blocked", "not_recorded")
    }
    meta["customerFieldsCompleteCount"] = sum(
        1 for packet in packets if tickets_by_key[packet.key].customer_fields_complete
    )
    meta["discovery"] = {
        "leadCount": sum(len(p.discovery.get("leads", [])) for p in packets),
        "passes": sorted({route for p in packets for route in p.discovery.get("passesRun", [])}),
        "leadsAreVerdicts": False,
    }
    meta["coverage"] = coverage
    meta["inputs"]["backlog"] = config.backlog_path or config.input_path
    meta["inputSha256"] = {
        name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for name, path in {
            "export": config.input_path,
            "backlog": config.backlog_path or config.input_path,
            **{
                f"assessment:{key}": str(Path(config.assessments_dir) / f"{key}.json")
                for key in selection
            },
            **{
                f"collection:{key}": str(Path(config.evidence_dir) / f"{key}.json")
                for key in collection
            },
            **(
                {"verification:index": str(Path(config.verification_dir) / "index.json")}
                if verification
                else {}
            ),
        }.items()
    }
    meta["codeSha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(Path(__file__).parent.glob("*.py"))
    }
    write_phased_output(
        output_dir,
        packets=packets,
        tickets=tickets_by_key,
        sample=sample,
        coverage=coverage,
        meta=meta,
        generated_at=generated_at,
        as_of=as_of.date().isoformat(),
        current_release=config.current_release,
        jql=jql,
        thresholds=thresholds,
        release_evidence=config.release_evidence,
        assessments_dir=config.assessments_dir,
    )

    return RunResult(
        packets=packets,
        tickets=tickets_by_key,
        sample=sample,
        manifest=meta,
        output_dir=output_dir,
    )
