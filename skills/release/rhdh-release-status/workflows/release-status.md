# Workflow: Release status

Every release-status question is one subcommand of `scripts/release.py`. Pick the
row, run it, present what it returns.

<prerequisites>

Jira reads use `acli`; `team-breakdown` also needs `gog`. When a command fails,
run `uv run scripts/release.py --json check` and follow its `next_steps`;
`references/config.md` documents the Rich Filter and Google Workspace setup it
points at. If Jira itself is unreachable, use the bundled Jira adapter for the reads
and say which figures stayed unverified.

</prerequisites>

<process>

## Step 1: Route the question

```bash
uv run scripts/release.py --json <subcommand>
```

| Question | Subcommand |
|---|---|
| Overall status, open issues by type | `status {{VERSION}}` |
| What is blocking the release | `blockers {{VERSION}}` |
| CVEs in scope | `cves {{VERSION}}` |
| Engineering EPICs still open | `epics {{VERSION}}` |
| Open issues per engineering team | `team-breakdown {{VERSION}}` |
| Release-note lifecycle (unclassified, proposed, done, with text) | `notes {{VERSION}}` |
| Work selected by the Post Code Freeze filter | `post-freeze {{VERSION}}` |
| Which queries the Rich Filter export exposes | `rich-filter inventory` |
| One exported entry, composed and counted | `rich-filter query <kind> <name>` |
| Whether the prerequisites hold | `check` |

Every subcommand except `check` and `rich-filter` takes the version as its one
positional argument. Ask for it when the request does not name one; do not
default to the newest release you happen to have seen.

`<kind>` is `static`, `smart`, `queue`, `time-series`, `ratio-numerator`, or
`ratio-denominator`. A smart-filter clause needs `--group "<group name>"`,
`--version` adds release scope, and `--count` executes the composed JQL. Both
sides of a custom ratio and every time series are executable; the dynamic fields
and view columns in the inventory are presentation metadata and are not.

## Step 2: Present the answer

One table per question — key, summary, status, priority, assignee, and team where
the CLI returns them — with `https://issues.redhat.com/browse/{{KEY}}` per row and
a URL-encoded `https://issues.redhat.com/issues/?jql=…` search link on each total.
Ask for counts, not full issue payloads, when only a total is wanted. Check
`truncated` before calling a number a total.

## Step 3 (fallback): CLI unavailable

`scripts/jql-release.md` holds the named templates behind the local
subcommands — `active_release`, `open_issues`, `open_issues_by_type`, `blockers`,
`epics`, `cves`, `open_issues_by_team`, `feature_subtasks`, and
`features_added_to_release` (scope added in the last 14 days). Invoke
the bundled Jira adapter with the matching template and take the counts from its result.

There is no fallback for `notes`, `post-freeze`, or `rich-filter`: the Rich
Filter export is the source of truth for release-note classification, Post Code
Freeze scope, and the freeze filters. If a template is unavailable, fix the
configuration and retry rather than substituting a hand-written query.

</process>

<gotchas>

- **After Code Freeze, only critical-severity CVEs are considered for inclusion
  before GA.** Give severity alongside the CVE count once a release has passed
  Code Freeze, or the raw total misleads.
- **EPICs in `Dev Complete` or `Release Pending` are excluded from the open EPIC
  count.** They count as finished for release tracking, so `epics` is
  deliberately smaller than a plain open-Epic search.
- `team-breakdown` filters on the Jira Cloud ID (`"Team[Team]" = "{{CLOUD_ID}}"`),
  not the team name. Cloud IDs come from the Rich Filter `Scrum Team` smart
  filter, falling back to the team spreadsheet.
- Announcement-scoped team counts use the freeze filters as their base query, not
  `open_issues_by_team`. Drafting the announcement is `/rhdh-release-announce`.
- Outstanding release notes are a documentation blocker before GA, not an
  informational number. The full process lives in
  [RHDH Release Notes Process](https://docs.google.com/document/d/1KFMkRVTkbDIhyZviZcuVn9UfJp64lKmokzT4ftMrj4w/edit).

</gotchas>

<success_criteria>

- [ ] The answer names the subcommand behind every number and when it was read
- [ ] Each count carries a Jira search link, each issue a browse link
- [ ] Truncated results are given as a floor, not a total
- [ ] Unavailable data is named as unverified rather than estimated

</success_criteria>
