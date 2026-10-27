"""ADF milestone date extraction — shared across release skills.

Single home for parsing Jira ADF (Atlassian Document Format) milestone tables
from RHDHPLAN release Feature descriptions.  Both rhdh-release-schedule and
rhdh-release-fixversions import from here instead of carrying their own copies.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

MILESTONE_LABELS = {
    "feature_freeze": r"\bFeature Freeze\b",
    "code_freeze": r"\bCode Freeze\b",
    "doc_freeze": r"\bDocs? Freeze\b",
    "go_no_go": r"\bGo/No Go\b",
    "ga_announce": r"\bGA Announce\b",
}


def adf_text(node: dict[str, Any]) -> str:
    """Render the text and date values from an Atlassian Document Format node."""
    if node.get("type") == "text":
        if any(mark.get("type") == "strike" for mark in node.get("marks", [])):
            return ""
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


def parse_natural_date(text: str) -> str | None:
    """Parse a natural-language date like 'August 24' or 'Sep 2 (done)'."""
    cleaned = re.sub(r"\(.*?\)", "", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return None
    year = datetime.now().year
    with_year = f"{cleaned}, {year}"
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(with_year, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def extract_milestone_dates(description: dict[str, Any] | str | None) -> dict[str, str]:
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
        if iso_match:
            date_str = iso_match.group(0)
        else:
            parts = line.split("|")
            date_str = parse_natural_date(parts[-1]) if len(parts) >= 2 else None
        if not date_str:
            continue
        for key, label_pattern in MILESTONE_LABELS.items():
            if re.search(label_pattern, line, re.IGNORECASE):
                dates[key] = date_str
                break
    return dates
