"""Select open, untriaged bugs in creation order."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from .model import (
    DEFAULT_AGED_DAYS,
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_SEED,
    TRIAGED_LABEL,
    Ticket,
    age_days,
    parse_datetime,
    validate_issue_key,
)


@dataclass
class Control:
    key: str
    label: str = ""


@dataclass
class SelectionConfig:
    size: int = DEFAULT_SAMPLE_SIZE
    aged_days: int = DEFAULT_AGED_DAYS
    seed: int = DEFAULT_SEED
    controls: List[Control] = field(default_factory=list)
    current_release: str = ""
    scope: str = "all-open"
    all_tickets: bool = False


@dataclass
class Selection:
    ticket: Ticket
    kind: str
    stratum: str
    age_days: Optional[int]
    control_label: str = ""

    def manifest_entry(self) -> Dict[str, object]:
        entry: Dict[str, object] = {
            "key": self.ticket.key,
            "kind": self.kind,
            "stratum": self.stratum,
            "ageDays": self.age_days,
            "summary": self.ticket.summary,
        }
        if self.control_label:
            entry["controlLabel"] = self.control_label
        return entry


def stratum_of(ticket: Ticket) -> str:
    if ticket.team:
        return ticket.team
    if ticket.components:
        return ticket.components[0]
    return "Unowned"


def exclusion_reason(ticket: Ticket, *legacy_selection_args) -> str:
    validate_issue_key(ticket.key)
    if not ticket.key.startswith("RHDHBUGS-"):
        return "outside RHDHBUGS project"
    if ticket.issue_type and ticket.issue_type.casefold() != "bug":
        return "issue type is not Bug"
    if TRIAGED_LABEL in ticket.labels:
        return f"already labelled {TRIAGED_LABEL}"
    if ticket.is_done:
        return f"done ({ticket.status or 'unknown status'})"
    if not ticket.status and not ticket.status_category:
        return "status unreadable; cannot establish an open issue"
    return ""


def select_sample(
    tickets: Iterable[Ticket],
    config: SelectionConfig,
    as_of: datetime,
) -> tuple[List[Selection], List[Dict[str, str]], int]:
    """Return selected tickets, exclusions, and the eligible population size."""
    if config.size < 0:
        raise ValueError("sample size must be nonnegative")
    by_key: Dict[str, Ticket] = {}
    for ticket in tickets:
        validate_issue_key(ticket.key)
        if ticket.key in by_key:
            raise ValueError(f"duplicate issue key in selection: {ticket.key}")
        by_key[ticket.key] = ticket

    control_keys = {control.key for control in config.controls}
    if len(control_keys) != len(config.controls):
        raise ValueError("duplicate control issue keys")
    for key in control_keys:
        validate_issue_key(key)
    eligible: List[Ticket] = []
    excluded: List[Dict[str, str]] = []
    for key in sorted(by_key):
        ticket = by_key[key]
        reason = exclusion_reason(ticket)
        if reason:
            # Report control exclusions once, in the control loop below.
            if key not in control_keys:
                excluded.append({"key": key, "reason": reason})
            continue
        eligible.append(ticket)

    eligible.sort(
        key=lambda t: (
            parse_datetime(t.created) or datetime.max.replace(tzinfo=timezone.utc),
            int(t.key.split("-")[1]),
        )
    )
    candidates = [t for t in eligible if t.key not in control_keys]
    if not config.all_tickets:
        candidates = candidates[: config.size]
    selected = [
        Selection(t, "all-open", stratum_of(t), age_days(t.created, as_of)) for t in candidates
    ]

    for control in config.controls:
        ticket = by_key.get(control.key)
        if ticket is None:
            excluded.append({"key": control.key, "reason": "control not present in the export"})
            continue
        reason = exclusion_reason(ticket)
        if reason:
            excluded.append(
                {
                    "key": control.key,
                    "reason": f"control is {reason}",
                }
            )
            continue
        selected.append(
            Selection(
                ticket=ticket,
                kind="control",
                stratum=stratum_of(ticket),
                age_days=age_days(ticket.created, as_of),
                control_label=control.label,
            )
        )

    return selected, excluded, len(eligible)
