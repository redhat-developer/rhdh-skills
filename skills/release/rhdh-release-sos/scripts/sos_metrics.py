"""Metric checks for SoS reports (ratios and percentages)."""

from __future__ import annotations

import re

_EPIC_DEV_COMPLETE = re.compile(
    r'^metric\s+epic_dev_complete\s+static\s+"([^"]+)"$',
    re.IGNORECASE,
)
_STATUS_NOT_IN = re.compile(r"\s+AND\s+status\s+not\s+in\s+\([^)]+\)", re.IGNORECASE)


def is_epic_dev_complete_query(query: str) -> bool:
    return _EPIC_DEV_COMPLETE.match(query.strip()) is not None


def epic_dev_complete_filter_name(query: str) -> str:
    match = _EPIC_DEV_COMPLETE.match(query.strip())
    if not match:
        raise ValueError(f"Not an epic dev complete metric query: {query!r}")
    return match.group(1)


def strip_status_exclusion(fragment: str) -> str:
    """Remove status-not-in from a Rich Filter fragment for all-status epic counts."""
    return _STATUS_NOT_IN.sub("", fragment).strip()


def build_epic_dev_complete_jql(
    filter_name: str,
    version: str,
    jql_mod,
    rf_mod,
    *,
    dev_complete_only: bool = False,
) -> str:
    """Compose JQL for Epics under a static filter scope."""
    fragment = rf_mod.static_filter(filter_name)
    if not fragment:
        raise ValueError(f'Rich Filter static filter not found: "{filter_name}"')
    epic_scope = strip_status_exclusion(fragment)
    extra_parts = ["issuetype = Epic"]
    if dev_complete_only:
        extra_parts.append('status = "Dev Complete"')
    return jql_mod.compose_fragment(
        epic_scope,
        version=version,
        extra=" AND ".join(extra_parts),
    )


def ratio_summary(numerator: int | None, denominator: int | None, *, status: str) -> str:
    if status == "unverified":
        return "Unverified"
    if not denominator:
        return "None"
    percent = round(numerator * 100 / denominator)
    return f"{percent}% ({numerator}/{denominator})"


def ratio_percent(numerator: int, denominator: int) -> int:
    if denominator == 0:
        return 0
    return round(numerator * 100 / denominator)
