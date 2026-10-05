"""Deterministic refinement signals (zero-token)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from _release import ReleaseContext

Issue = dict


@dataclass(frozen=True)
class SignalResult:
    signal_id: str
    section: str
    emoji: str
    keys: list[str]
    message: str
    suffix: str = ""
    jql: str = ""


def _keys_where(issues: list[Issue], pred: Callable[[Issue], bool]) -> list[str]:
    return [i["key"] for i in issues if pred(i)]


def evaluate_signals(
    issues: list[Issue],
    *,
    epic_without_children: list[str],
    release: ReleaseContext,
    team_id: str,
    queue_jql: str,
) -> list[SignalResult]:
    """Return only signals with count > 0."""
    results: list[SignalResult] = []

    epic_keys = _keys_where(issues, lambda i: i["key"] in epic_without_children)
    if epic_keys:
        label = "Epic" if len(epic_keys) == 1 else "Epics"
        need = "needs" if len(epic_keys) == 1 else "need"
        results.append(
            SignalResult(
                signal_id="epic_no_children",
                section="features",
                emoji="📐",
                keys=epic_keys,
                message=f"{len(epic_keys)} {label} {need} breakdown",
                suffix="no child stories",
                jql=_key_in_jql(epic_keys),
            )
        )

    unassigned = _keys_where(issues, lambda i: not i["assigned"])
    if unassigned:
        results.append(
            SignalResult(
                signal_id="unassigned",
                section="work_readiness",
                emoji="👤",
                keys=unassigned,
                message=f"{len(unassigned)} issues need an owner",
                jql=_queue_and(queue_jql, "assignee is EMPTY"),
            )
        )

    def needs_sp(i: Issue) -> bool:
        if i["issuetype"] in ("Epic", "Feature"):
            return False
        return i["story_points"] is None or i["story_points"] == ""

    unsized = _keys_where(issues, needs_sp)
    if unsized:
        word = "issue" if len(unsized) == 1 else "issues"
        need = "needs" if len(unsized) == 1 else "need"
        results.append(
            SignalResult(
                signal_id="missing_story_points",
                section="work_readiness",
                emoji="📏",
                keys=unsized,
                message=f"{len(unsized)} {word} {need} sizing",
                suffix="Story Points missing",
                jql=_key_in_jql(unsized),
            )
        )

    no_priority = _keys_where(issues, lambda i: i["priority"] in ("", "Undefined"))
    if no_priority:
        results.append(
            SignalResult(
                signal_id="priority_unset",
                section="hygiene",
                emoji="⚡",
                keys=no_priority,
                message=f"{len(no_priority)} issues have no Priority",
                jql=_queue_and(queue_jql, "priority = Undefined"),
            )
        )

    flagged = {k for sig in results for k in sig.keys}
    clear = [i["key"] for i in issues if i["key"] not in flagged]
    if clear:
        results.append(
            SignalResult(
                signal_id="no_detected_gaps",
                section="clear",
                emoji="✅",
                keys=clear,
                message=f"{len(clear)} issues have no detected gaps",
                jql=_key_in_jql(clear),
            )
        )

    return results


def build_facts(
    issues: list[Issue],
    signals: list[SignalResult],
    release: ReleaseContext,
    queue_jql: str,
) -> dict:
    by_id = {s.signal_id: s.keys for s in signals}
    overlaps: list[dict] = []
    key_to_signals: dict[str, list[str]] = {}
    for sig in signals:
        if sig.signal_id == "no_detected_gaps":
            continue
        for key in sig.keys:
            key_to_signals.setdefault(key, []).append(sig.signal_id)
    for key, ids in sorted(key_to_signals.items()):
        if len(ids) > 1:
            overlaps.append({"key": key, "signals": ids})

    return {
        "release": {
            "primary_version": release.primary_version,
            "secondary_version": release.secondary_version,
            "candidate_label": release.candidate_label,
            "code_freeze": release.code_freeze_date.isoformat() if release.code_freeze_date else None,
            "freeze_days": release.days_to_code_freeze,
            "freeze_warning": release.freeze_warning,
        },
        "queue": {
            "total": len(issues),
            "jql": queue_jql,
            "keys": [i["key"] for i in issues],
        },
        "signals": by_id,
        "overlaps": overlaps,
    }


def _key_in_jql(keys: list[str]) -> str:
    joined = ",".join(keys)
    return f"key in ({joined})"


def _queue_and(queue_jql: str, clause: str) -> str:
    return f"{queue_jql} AND {clause}"
