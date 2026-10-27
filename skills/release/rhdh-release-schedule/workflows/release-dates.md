# Workflow: RHDH release dates

Two sources hold RHDH milestone dates. Which one to read follows from the
version, not from the way the question was asked.

| Source | Subcommand | Covers | Milestones |
|---|---|---|---|
| Jira — the RHDHPLAN release Feature | `dates` | releases currently in flight | Feature Freeze, Code Freeze, Docs Input Freeze, Docs Freeze, Go/No Go & Push, GA announce |
| Google Sheets — RHDH release schedule | `future-dates {{VERSION}}` | planned releases, including ones with no Jira issue yet | Feature Freeze, Code Freeze, GA |

<prerequisites>

`dates` needs `acli` with a Jira session; `future-dates` needs `gog`. Run
`uv run scripts/release.py --json check` when either fails and follow its
`next_steps`. If the Jira capability is missing, direct the user to
`/setup-rhdh-skills jira`; for `gog`, to `/setup-rhdh-skills google-workspace`.

</prerequisites>

<process>

## Step 1: Try Jira first

```bash
uv run scripts/release.py --json dates
```

This returns every active release with all six milestones. If the requested
version is in that output, it is the answer — the Jira release issue is
maintained by the release manager and is the more current of the two sources.

## Step 2: Fall back to the schedule sheet

When the version is not among the active releases, or the request is explicitly
about a future one:

```bash
uv run scripts/release.py --json future-dates {{VERSION}}
```

The sheet is the only source for versions that have no release issue yet. Ask
which version the user means when the request names none; do not answer for every
release at once unless that is what was asked.

## Step 3: Present the dates

One row per release, every milestone the source carries, and the source link:

| Release | Feature Freeze | Code Freeze | Docs Freeze | Go/No Go | GA | Source |
|---|---|---|---|---|---|---|

Use `https://issues.redhat.com/browse/{{ISSUE_KEY}}` for a Jira-sourced row and
the [RHDH release schedule](https://docs.google.com/spreadsheets/d/1knVzlMW0l0X4c7gkoiuaGql1zuFgEGwHHBsj-ygUTnc/edit)
for a sheet-sourced one. When both sources cover the same version and disagree,
show both rows and flag the conflict; do not pick a winner.

## Step 4 (fallback): CLI unavailable

For Jira, use the bundled Jira adapter with the `active_release` template from
`scripts/jql-release.md`, then ask it for each returned issue's description.
The dates live in a table inside the description, not in custom fields — read the
milestone rows, and treat a date cell that is plain text rather than a date node
as TBD.

For the sheet, find the tab whose name carries the current year and "schedule"
with `gog sheets metadata 1knVzlMW0l0X4c7gkoiuaGql1zuFgEGwHHBsj-ygUTnc --json`,
fetch it with `gog sheets get <id> "{{TAB_NAME}}" --json --results-only`, locate
the target version's GA row, then walk backwards to Code Freeze and Feature
Freeze.

</process>

<gotchas>

- Jira dates are embedded in the release issue's description table. Parse the
  description; there are no milestone custom fields.
- Milestones are routinely TBD. Report TBD as TBD.
- `future-dates` reads only the first schedule tab matching the current year, so a
  version scheduled in a later year may be missing from its output.
- `{"error": "version_not_found"}` means the version string in the sheet differs
  from the one asked for — ask the user for the exact string rather than guessing
  a normalisation.
- `{"error": "spreadsheet_not_found"}` means access, not absence. Ask the user to
  share the sheet.

</gotchas>

<success_criteria>

- [ ] Every date carries the Jira issue key or the schedule sheet as its source
- [ ] TBD milestones are shown as TBD
- [ ] A version covered by both sources with conflicting dates shows both

</success_criteria>
