"""Evaluate refinement signals from queue issues."""

from __future__ import annotations

from dataclasses import dataclass
from _release import ReleaseContext


@dataclass(frozen=True)
class Signal:
    name: str
    keys: list[str]
    jql: str


def evaluate(
    issues: list[dict],
    *,
    queue_jql: str,
    release: ReleaseContext,
) -> list[Signal]:
    signals: list[Signal] = []
    unassigned = [i["key"] for i in issues if not i.get("assigned")]
    if unassigned:
        signals.append(Signal("unassigned", unassigned, f"{queue_jql} AND assignee is EMPTY"))
    unsized = [i["key"] for i in issues if i.get("story_points") is None]
    if unsized:
        signals.append(Signal("unsized", unsized, f'{queue_jql} AND "Story Points" is EMPTY'))
    no_priority = [i["key"] for i in issues if (i.get("priority") or "").lower() in ("undefined", "")]
    if no_priority:
        signals.append(Signal("no_priority", no_priority, f"{queue_jql} AND priority = Undefined"))
    epics_no_children = [
        i["key"] for i in issues
        if i.get("issuetype") == "Epic" and i.get("no_children")
    ]
    if epics_no_children:
        signals.append(Signal("epic_no_children", epics_no_children, f"parent in ({','.join(epics_no_children)}) AND status != Closed"))
    return signals


def build_facts(
    issues: list[dict],
    signals: list[Signal],
    release: ReleaseContext,
    queue_jql: str,
) -> dict:
    by_name = {s.name: s.keys for s in signals}
    key_signals: dict[str, list[str]] = {}
    for s in signals:
        for k in s.keys:
            key_signals.setdefault(k, []).append(s.name)
    overlaps = [
        {"key": k, "signals": sigs}
        for k, sigs in sorted(key_signals.items())
        if len(sigs) > 1
    ]
    return {
        "release": {
            "version": release.version,
            "code_freeze": release.code_freeze.isoformat() if release.code_freeze else None,
            "feature_freeze": release.feature_freeze.isoformat() if release.feature_freeze else None,
            "freeze_days": release.days_to_code_freeze,
            "phase": release.phase,
        },
        "queue": {"total": len(issues), "jql": queue_jql},
        "signals": by_name,
        "overlaps": overlaps,
    }
