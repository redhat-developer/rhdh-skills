# SoS configuration

## Prerequisites

Jira reads and Rich Filter queries reuse `/rhdh-release-status` scripts through
`_release_bridge.py`. Install both skills from the release category.

Run:

```bash
uv run scripts/sos_report.py --json check
```

That delegates to the release-status prerequisite check (`acli`, Rich Filter contract).

## Rich Filter

The check runbook composes queries from the same RHIDP Operational export as
`/rhdh-release-status`. Register private data with `/setup-rhdh-skills` and set
`RHDH_RICH_FILTER_PATH` when needed. When a query fails because the export is
missing, name `/rhdh-release-status` and retry after configuration — do not
substitute hand-written JQL.

## Editing checks

Add or reorder rows in `references/sos-checks.md`. Keep section headers and check
rows in chronological order within each section. See `references/timeline.md` for
`When` syntax and the cumulative rule.
