# SoS timeline rules

## Milestone sections

The runbook table uses section headers that match release milestones:

| Header | Milestone key |
|---|---|
| Feature Freeze | `feature_freeze` |
| Code Freeze | `code_freeze` |
| Go/No Go | `go_no_go` |
| GA Announce | `ga_announce` |

The active section follows the calendar:

- before Feature Freeze → **Feature Freeze** section
- Feature Freeze ≤ today < Code Freeze → **Code Freeze** section
- Code Freeze ≤ today < Go/No Go → **Go/No Go** section
- on or after Go/No Go → **GA Announce** section

Milestone dates come from the active RHDHPLAN release Feature in Jira via
`/rhdh-release-schedule`. This skill does not read the schedule spreadsheet directly.

## When column syntax

| Form | Example | Resolves to |
|---|---|---|
| Milestone offset | `FF - 21d` | Feature Freeze date minus 21 days |
| Milestone offset | `CF - 7d` | Code Freeze date minus 7 days |
| Absolute date | `2026-09-08` | That calendar day |

Supported milestone labels: `FF`, `CF`, `GNG`, `GA`, or the full header names.

## Cumulative execution

Within the active section only:

1. Resolve each check row to a calendar date.
2. Run checks whose resolved date is **≤ today**.
3. Do not run checks whose resolved date is **> today**.
4. List skipped future rows under **Upcoming checks** in the report.

Checks in later sections never run early.
