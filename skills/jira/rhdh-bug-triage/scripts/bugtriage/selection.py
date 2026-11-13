"""Deterministic, customer-safe sample selection.

The sample is stratified by team (or the first component when Team is absent)
and ordered by a stable hash, so two people with the same export and seed get
the same ticket list on any machine. Customer-linked tickets are excluded from
normal sampling and from the control set: this skill never proposes closing a
customer bug.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from .model import (
    DEFAULT_AGED_DAYS,
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_SEED,
    Ticket,
    age_days,
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
    """Return the first customer signal, or an empty string."""
    return ticket.customer_signals[0] if ticket.customer_signals else ""


def stratum_of(ticket: Ticket) -> str:
    if ticket.team:
        return ticket.team
    if ticket.components:
        return ticket.components[0]
    return "Unowned"


def exclusion_reason(ticket: Ticket, as_of: datetime, aged_days: int) -> str:
    if customer_reason(ticket):
        return f"customer-linked ({customer_reason(ticket)})"
    if ticket.is_done:
        return f"done ({ticket.status or 'unknown status'})"
    age = age_days(ticket.created, as_of)
    if age is None:
        return "created date unreadable"
    if age < aged_days:
        return f"younger than {aged_days}d ({age}d)"
    return ""


def _stable_order(key: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


def select_sample(
    tickets: Iterable[Ticket],
    config: SelectionConfig,
    as_of: datetime,
) -> tuple[List[Selection], List[Dict[str, str]], int]:
    """Return selected tickets, exclusions, and the eligible population size."""
    by_key: Dict[str, Ticket] = {}
    for ticket in tickets:
        by_key.setdefault(ticket.key, ticket)

    control_keys = {control.key for control in config.controls}
    eligible: List[Ticket] = []
    excluded: List[Dict[str, str]] = []
    for key in sorted(by_key):
        ticket = by_key[key]
        reason = exclusion_reason(ticket, as_of, config.aged_days)
        if reason:
            # A control may legitimately be Done, young, or otherwise ineligible
            # for the aged sample. The control loop below decides whether to
            # include or refuse it; do not also report it as excluded.
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
    while len(selected) < config.size and any(strata.values()):
        name = ordered_strata[cursor % len(ordered_strata)]
        group = strata[name]
        if group:
            ticket = group.pop(0)
            if ticket.key not in control_keys:
                selected.append(
                    Selection(
                        ticket=ticket,
                        kind="aged",
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
        if customer_reason(ticket):
            excluded.append(
                {
                    "key": control.key,
                    "reason": f"control is customer-linked ({customer_reason(ticket)})",
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
