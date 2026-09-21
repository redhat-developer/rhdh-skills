"""ADF milestone date extraction — shared across release skills.

Single home for parsing Jira ADF (Atlassian Document Format) milestone tables
from RHDHPLAN release Feature descriptions.  Both rhdh-release-schedule and
rhdh-release-fixversions import from here instead of carrying their own copies.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

MILESTONE_LABELS = {
    "feature_freeze": r"\bFeature Freeze\b",
    "code_freeze": r"\bCode Freeze\b",
    "doc_freeze": r"\bDocs? Freeze\b",
    "go_no_go": r"\bGo/No Go\b",
    "ga_announce": r"\bGA Announce\b",
}

_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_NATURAL_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August"
    r"|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?\b",
    re.IGNORECASE,
)


def _parse_natural_date(text: str, reference_year: int | None = None) -> str | None:
    """Parse 'September 14', 'Sep 14, 2026', etc. into an ISO date string."""
    match = _NATURAL_DATE_RE.search(text)
    if not match:
        return None
    month = _MONTH_NAMES.get(match.group(1).lower())
    day = int(match.group(2))
    year = (
        int(match.group(3))
        if match.group(3)
        else (reference_year or datetime.now(timezone.utc).year)
    )
    if not month:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def adf_text(node: dict[str, Any]) -> str:
    """Render the text and date values from an Atlassian Document Format node."""
    if node.get("type") == "text":
        return node.get("text", "")
    if node.get("type") == "date":
        try:
            timestamp = int(node.get("attrs", {}).get("timestamp"))
            return datetime.fromtimestamp(timestamp / 1000, timezone.utc).date().isoformat()
        except (TypeError, ValueError, OverflowError):
            return ""
    return " ".join(filter(None, (adf_text(child) for child in node.get("content", []))))


def adf_table_rows(node: dict[str, Any]) -> list[str]:
    """Return rendered rows from an ADF document's tables."""
    rows: list[str] = []
    if node.get("type") == "tableRow":
        rows.append(" | ".join(adf_text(cell).strip() for cell in node.get("content", [])))
    for child in node.get("content", []):
        rows.extend(adf_table_rows(child))
    return rows


def extract_milestone_dates(
    description: dict[str, Any] | str | None,
    reference_year: int | None = None,
) -> dict[str, str]:
    """Parse the milestone table embedded in a release Feature description."""
    dates = {key: "TBD" for key in MILESTONE_LABELS}
    if isinstance(description, dict):
        lines = adf_table_rows(description)
    elif isinstance(description, str):
        lines = description.splitlines()
    else:
        return dates

    for line in lines:
        iso_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", line)
        date_str = iso_match.group(0) if iso_match else _parse_natural_date(line, reference_year)
        if not date_str:
            continue
        for key, label_pattern in MILESTONE_LABELS.items():
            if re.search(label_pattern, line, re.IGNORECASE):
                dates[key] = date_str
                break
    return dates
