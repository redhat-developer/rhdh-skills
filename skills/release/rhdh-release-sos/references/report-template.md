# SoS report template

The CLI fills this template exactly. Do not add sections, reorder headings, or
improvise prose around it.

```markdown
# RHDH {{VERSION}} — SoS Release Check-in

| | |
|---|---|
| As of | {{AS_OF}} |
| Release phase | {{ACTIVE_SECTION}} |
| Next milestone | {{NEXT_MILESTONE}} |

## Milestones

| Milestone | Date | Days remaining |
|---|---|---:|
| Feature Freeze | {{FF_DATE}} | {{FF_DAYS}} |
| Code Freeze | {{CF_DATE}} | {{CF_DAYS}} |
| Go/No Go | {{GNG_DATE}} | {{GNG_DAYS}} |
| GA Announce | {{GA_DATE}} | {{GA_DAYS}} |

## Checks

| Check | Summary | Jira |
|---|---|---|
{{CHECK_ROWS}}
```

Each due check uses one or more table rows:

```markdown
| {{CHECK_TITLE}} | {{CHECK_SUMMARY}} | [Open in Jira]({{JIRA_URL}}) |
| ↳ ℹ {{ACTION_ITEM}} | | |
| ↳ {{TEAM_NAME}} | {{TEAM_SUMMARY}} | [Open in Jira]({{TEAM_JIRA_URL}}) |
```

Omit the `↳ ℹ …` row when the runbook leaves Action item blank. Team sub-rows use
engineering teams from the RHDH Team Mapping spreadsheet with a Jira Cloud ID. The
team filter is the same check query plus `"Team[Team]" = "<cloud_id>"`. Omit teams
without a Cloud ID.

When no checks are due:

```markdown
| _No checks due today._ | | |
```

Summary values are only: `None open`, `1 open`, `N open`, `Unverified`, ratio
summaries, or expect-assignee summaries (`Assigned (KEY)`, `Unassigned — find an
owner`, `Not found — create or link ticket`, `Multiple matches (…)`).

Present `report_markdown` from the CLI without editing. Issue-list checks appear in the
Checks table like count checks, with team sub-rows. Do not append runbook metadata, upcoming checks, follow-up bullet lists, or a
separate narrative summary.
