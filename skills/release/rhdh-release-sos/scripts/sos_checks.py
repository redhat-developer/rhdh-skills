"""Parse the SoS check runbook table from references/sos-checks.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

_RELATIVE_WHEN = re.compile(
    r"^(?P<label>FF|CF|GNG|GA|Feature Freeze|Code Freeze|Go/No Go|GA Announce)"
    r"\s*-\s*(?P<days>\d+)d$",
    re.IGNORECASE,
)
_ABSOLUTE_WHEN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_MILESTONE_KEYS = {
    "ff": "feature_freeze",
    "feature freeze": "feature_freeze",
    "cf": "code_freeze",
    "code freeze": "code_freeze",
    "gng": "go_no_go",
    "go/no go": "go_no_go",
    "ga": "ga_announce",
    "ga announce": "ga_announce",
}

_SECTION_HEADERS = {
    "feature freeze": "feature_freeze",
    "code freeze": "code_freeze",
    "go/no go": "go_no_go",
    "ga announce": "ga_announce",
}

_SECTION_ORDER = [
    ("feature_freeze", "Feature Freeze"),
    ("code_freeze", "Code Freeze"),
    ("go_no_go", "Go/No Go"),
    ("ga_announce", "GA Announce"),
]


@dataclass(frozen=True)
class SectionHeader:
    title: str
    milestone_key: str


@dataclass(frozen=True)
class CheckRow:
    section: SectionHeader
    when_raw: str
    title: str
    query: str
    action_item: str = ""
    resolved_date: date | None = None


def checks_path(base: Path | None = None) -> Path:
    root = base or Path(__file__).resolve().parents[1]
    return root / "references" / "sos-checks.md"


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return cells


def _is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-+:?", cell.replace(" ", "")) for cell in cells if cell)


def parse_checks(text: str) -> list[SectionHeader | CheckRow]:
    """Parse the runbook markdown table into section headers and check rows."""
    rows: list[SectionHeader | CheckRow] = []
    current_section: SectionHeader | None = None
    in_table = False

    for line in text.splitlines():
        cells = _split_table_row(line)
        if len(cells) < 3:
            continue
        if cells[0].lower() == "when" and cells[1].lower() == "check":
            in_table = True
            continue
        if not in_table or _is_separator_row(cells):
            continue

        when_raw, title, query = cells[0], cells[1], cells[2]
        action_item = cells[3].strip() if len(cells) > 3 else ""
        header_key = _SECTION_HEADERS.get(when_raw.strip().lower())
        if header_key and not title and not query:
            current_section = SectionHeader(title=when_raw.strip(), milestone_key=header_key)
            rows.append(current_section)
            continue
        if current_section is None:
            raise ValueError(f"Check row before any section header: {when_raw!r}")
        if not title or not query:
            continue
        rows.append(
            CheckRow(
                section=current_section,
                when_raw=when_raw.strip(),
                title=title.strip(),
                query=query.strip(),
                action_item=action_item,
            )
        )

    if not rows:
        raise ValueError("No SoS checks found in sos-checks.md")
    return rows


def load_checks(base: Path | None = None) -> list[SectionHeader | CheckRow]:
    path = checks_path(base)
    return parse_checks(path.read_text(encoding="utf-8"))


def _parse_iso(value: str) -> date:
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def resolve_when(when_raw: str, milestones: dict[str, str]) -> date:
    """Resolve a When cell to a concrete calendar date."""
    if _ABSOLUTE_WHEN.match(when_raw):
        return _parse_iso(when_raw)

    match = _RELATIVE_WHEN.match(when_raw)
    if not match:
        raise ValueError(f"Unsupported When value: {when_raw!r}")

    milestone_key = _MILESTONE_KEYS[match.group("label").strip().lower()]
    milestone_date = milestones.get(milestone_key, "TBD")
    if milestone_date in ("", "TBD", "N/A"):
        raise ValueError(
            f"Cannot resolve {when_raw!r}: milestone {milestone_key} is {milestone_date!r}"
        )
    offset_days = int(match.group("days"))
    anchor = _parse_iso(milestone_date)
    return anchor - timedelta(days=offset_days)


def attach_dates(
    rows: list[SectionHeader | CheckRow], milestones: dict[str, str]
) -> list[SectionHeader | CheckRow]:
    resolved: list[SectionHeader | CheckRow] = []
    for row in rows:
        if isinstance(row, SectionHeader):
            resolved.append(row)
            continue
        resolved.append(
            CheckRow(
                section=row.section,
                when_raw=row.when_raw,
                title=row.title,
                query=row.query,
                action_item=row.action_item,
                resolved_date=resolve_when(row.when_raw, milestones),
            )
        )
    return resolved


def current_section_key(as_of: date, milestones: dict[str, str]) -> str:
    """Return the milestone section that contains as_of."""
    ordered: list[tuple[str, date]] = []
    for key, _title in _SECTION_ORDER:
        raw = milestones.get(key, "TBD")
        if raw in ("", "TBD", "N/A"):
            continue
        ordered.append((key, _parse_iso(raw)))

    if not ordered:
        raise ValueError("No milestone dates available to determine the current section")

    if as_of <= ordered[0][1]:
        return ordered[0][0]

    for index in range(len(ordered) - 1):
        start, end = ordered[index][1], ordered[index + 1][1]
        if start < as_of <= end:
            return ordered[index + 1][0]

    return ordered[-1][0]


def select_checks(
    rows: list[SectionHeader | CheckRow],
    *,
    as_of: date,
    milestones: dict[str, str],
) -> tuple[list[CheckRow], list[CheckRow], SectionHeader]:
    """Return due checks, upcoming checks, and the active section header."""
    section_key = current_section_key(as_of, milestones)
    section_title = next(title for key, title in _SECTION_ORDER if key == section_key)
    active_section = SectionHeader(title=section_title, milestone_key=section_key)

    due: list[CheckRow] = []
    upcoming: list[CheckRow] = []
    section_rows = [
        row
        for row in rows
        if isinstance(row, CheckRow) and row.section.milestone_key == section_key
    ]
    for row in section_rows:
        if row.resolved_date is None:
            raise ValueError(f"Check {row.title!r} has no resolved date")
        if row.resolved_date <= as_of:
            due.append(row)
            continue
        upcoming.append(row)

    return due, upcoming, active_section
