"""Cross-signal Noticed block (deterministic, zero-token)."""

from __future__ import annotations

_SIGNAL_LABELS = {
    "epic_no_children": "breakdown",
    "unassigned": "owner",
    "missing_story_points": "sizing",
    "priority_unset": "priority",
}


def render_noticed(facts: dict, jira_base: str) -> list[str] | None:
    """Return markdown lines for ## ✨ Noticed, or None if nothing to add."""
    signals = facts.get("signals") or {}
    release = facts.get("release") or {}
    freeze_days = release.get("freeze_days")
    bullets: list[str] = []

    epic_keys = set(signals.get("epic_no_children") or [])
    unassigned = set(signals.get("unassigned") or [])
    priority_keys = set(signals.get("priority_unset") or [])
    sizing_keys = set(signals.get("missing_story_points") or [])

    for key in sorted(epic_keys & unassigned):
        if freeze_days is not None and freeze_days <= 14:
            bullets.append(
                _bullet(
                    jira_base,
                    key,
                    f"concentrates **{release.get('primary_version', 'release')}** risk — "
                    f"unowned Epic with no child work and **{freeze_days} days** to code freeze.",
                )
            )

    overlaps = facts.get("overlaps") or []
    for item in overlaps:
        key = item["key"]
        if key in epic_keys & unassigned and freeze_days is not None and freeze_days <= 14:
            continue
        labels = ", ".join(_SIGNAL_LABELS.get(s, s) for s in item.get("signals", []))
        bullets.append(
            _bullet(
                jira_base,
                key,
                f"shows up in multiple signals ({labels}) — one issue, several warnings.",
            )
        )

    readiness = unassigned | sizing_keys | epic_keys
    hygiene_only = priority_keys - readiness
    if len(hygiene_only) >= 3 and readiness:
        bullets.append(
            f"**Priority gaps are mostly field-level** ({len(hygiene_only)} issues); "
            f"ownership and sizing are the stronger signals before refinement."
        )

    if not bullets:
        return None

    unique: list[str] = []
    for line in bullets[:3]:
        if line not in unique:
            unique.append(line)

    return ["## ✨ Noticed", ""] + unique + [""]


def _bullet(jira_base: str, key: str, text: str) -> str:
    url = f"{jira_base.rstrip('/')}/browse/{key}"
    return f"**[{key}]({url})** {text}"
