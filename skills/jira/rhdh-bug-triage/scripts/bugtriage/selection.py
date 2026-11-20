"""Deterministic, customer-safe sample selection.

The sample is stratified by team (or the first component when Team is absent)
and ordered by a stable hash, so two people with the same export and seed get
the same ticket list on any machine. Customer-linked tickets are excluded from
normal sampling and from the control set: this skill never proposes closing a
customer bug.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from .model import (
    DEFAULT_AGED_DAYS,
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_SEED,
    Ticket,
    age_days,
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
    scope: str = "aged"
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


def customer_reason(ticket: Ticket) -> str:
    """Prefer a cited relationship over populated-field screening metadata."""
    return next(
        (signal for signal in ticket.customer_signals if not signal.startswith("field:")),
        ticket.customer_signals[0] if ticket.customer_signals else "",
    )


def stratum_of(ticket: Ticket) -> str:
    if ticket.team:
        return ticket.team
    if ticket.components:
        return ticket.components[0]
    return "Unowned"


def _release_tuple(value: str) -> Optional[tuple[int, int, int]]:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", value.strip())
    return tuple(int(part or 0) for part in match.groups()) if match else None


def _validate_scope(current_release: str, scope: str, aged_days: int) -> None:
    if scope not in {"aged", "all-open"}:
        raise ValueError(f"unknown selection scope: {scope!r}")
    if scope == "aged":
        if _release_tuple(current_release) is None:
            raise ValueError("aged selection requires a parseable current_release")
        if aged_days < DEFAULT_AGED_DAYS:
            raise ValueError(f"aged selection requires at least {DEFAULT_AGED_DAYS}d")


def _base_exclusion(ticket: Ticket) -> str:
    validate_issue_key(ticket.key)
    if not ticket.key.startswith("RHDHBUGS-"):
        return "outside RHDHBUGS project"
    signal = customer_reason(ticket)
    if signal:
        if signal.startswith("field:"):
            return f"customer-field precaution ({signal}; populated metadata is not proof of a customer case)"
        return f"customer-linked ({signal})"
    if ticket.is_done:
        return f"done ({ticket.status or 'unknown status'})"
    if not ticket.status and not ticket.status_category:
        return "status unreadable; cannot establish an open issue"
    return ""


def exclusion_reason(
    ticket: Ticket,
    as_of: datetime,
    aged_days: int,
    current_release: str = "",
    scope: str = "aged",
) -> str:
    _validate_scope(current_release, scope, aged_days)
    reason = _base_exclusion(ticket)
    if reason or scope == "all-open":
        return reason
    age = age_days(ticket.created, as_of)
    if age is None:
        return "created date unreadable"
    if age < aged_days:
        return f"younger than {aged_days}d ({age}d)"
    if ticket.affects_versions_ambiguous:
        return "affects versions contain ambiguous or unreadable values"
    if not ticket.affects_versions:
        return "affects versions missing; aged scope requires versions older than the release under review"
    current = _release_tuple(current_release)
    for version in ticket.affects_versions:
        parsed = _release_tuple(version)
        if parsed is None:
            return f"affects version ambiguous or unreadable ({version!r})"
        if parsed >= current:
            return f"affects version {version} is not older than the release under review ({current_release})"
    return ""


def _stable_order(key: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


def select_sample(
    tickets: Iterable[Ticket],
    config: SelectionConfig,
    as_of: datetime,
) -> tuple[List[Selection], List[Dict[str, str]], int]:
    """Return selected tickets, exclusions, and the eligible population size."""
    _validate_scope(config.current_release, config.scope, config.aged_days)
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
        reason = exclusion_reason(
            ticket, as_of, config.aged_days, config.current_release, config.scope
        )
        if reason:
            # Controls may bypass age/version filters, but not the base safety
            # filters. Report them once, in the control loop below.
            if key not in control_keys:
                excluded.append({"key": key, "reason": reason})
            continue
        eligible.append(ticket)

    strata: Dict[str, List[Ticket]] = {}
    for ticket in eligible:
        strata.setdefault(stratum_of(ticket), []).append(ticket)
    for group in strata.values():
        group.sort(key=lambda item: (_stable_order(item.key, config.seed), item.key))

    selected: List[Selection] = []
    # Round-robin keeps a large team from owning the whole sample.
    ordered_strata = sorted(strata)
    cursor = 0
    target_size = len(eligible) if config.all_tickets else config.size
    while len(selected) < target_size and any(strata.values()):
        name = ordered_strata[cursor % len(ordered_strata)]
        group = strata[name]
        if group:
            ticket = group.pop(0)
            if ticket.key not in control_keys:
                selected.append(
                    Selection(
                        ticket=ticket,
                        kind=config.scope,
                        stratum=name,
                        age_days=age_days(ticket.created, as_of),
                    )
                )
        cursor += 1
        if not any(strata.values()):
            break

    for control in config.controls:
        ticket = by_key.get(control.key)
        if ticket is None:
            excluded.append({"key": control.key, "reason": "control not present in the export"})
            continue
        reason = _base_exclusion(ticket)
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
