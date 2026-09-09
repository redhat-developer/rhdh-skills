# Jira authenticated API fallback

Use this seam only when `acli` cannot read or update a required Jira field. This reference defines
payload semantics. Credentials stay inside an already-authenticated host adapter or the bundled
token-file adapter (`scripts/greenhopper.py`). Public output never includes them.

## Capability gate

1. Try the supported `acli` operation first. For broad reads, use paginated search; for a single
   issue, use `acli jira workitem view KEY --fields '*all' --json`.
2. For Greenhopper sprint reports, run `uv run scripts/setup.py --json` and, when
   `token_file_found` is true, `uv run scripts/greenhopper.py sprintreport --board ID --sprint ID`.
   That script reads the token file in-process. The agent never `cat`s the file, never sets `AUTH`,
   and never calls `curl`.
3. For other fields `acli` cannot handle, use REST only through an already-authenticated host
   Atlassian adapter. The adapter owns the site, credential store, request headers, retries, and
   secret redaction.
4. If that adapter is unavailable and the bundled Greenhopper script cannot run, say which field
   could not be read and tell the human to run `/setup-rhdh-skills atlassian-mcp` (host adapter) or
   skip Greenhopper and reconstruct.

Do not create token files, shell `AUTH` variables, Authorization headers, or credential-bearing
request previews in model context. Do not fall back from a native tool to raw `curl`.

## Supported semantic operations

| Operation | Request semantics | Expected result |
|---|---|---|
| Read all fields | Get issue by key with `fields=*all` | Issue object |
| Discover fields | List Jira fields | Field IDs, types, and names |
| Check editability | Get edit metadata for an issue | Allowed operations and values |
| Update fields | Partial issue update with a `fields` object | No-content success or updated issue |
| Add comment | Add an ADF comment, with visibility when required | Comment receipt |
| Add remote link | Attach a web link to an issue key with `{"object": {"url": ..., "title": ...}}` | Created link with an id, or the id of the link it replaced |
| Sprint report (best-effort) | GET Greenhopper `sprintreport` via `scripts/greenhopper.py` | Per-sprint completed / not-completed issues, estimate sums, `issueKeysAddedDuringSprint`, `issuesCompletedInAnotherSprint` |
| Scope-change burndown (best-effort) | GET Greenhopper `scopechangeburndownchart` via `scripts/greenhopper.py` | Timestamped estimate and scope-change events |

The host adapter may expose these as tools instead of URL paths. Select by semantic capability, not
by tool name, and keep transport-specific response metadata out of what you report.

## Remote links

A remote link is the "web link" shown on a Jira issue. It is the supported way to record an
external URL — a pull request, a design document, a support case — against an issue, and `acli`
has no equivalent, so the authenticated adapter owns it.

```json
{"object": {"url": "https://github.com/redhat-developer/rhdh/pull/1234", "title": "GitHub PR: Fix plugin loader"}}
```

The target is the issue key; `object.url` and `object.title` are the whole payload. A second link
carrying the same URL replaces the first rather than creating a duplicate, so re-running after a
partial failure is safe. Report the link id the adapter returns.

A caller handing over a pull request usually wants three writes at once — a comment, a transition
to `Review`, and a remote link to the PR URL. Present all three together so a single approval
covers the set. `/rhdh-jira-update` owns that flow.

## Custom-field payloads

These are payload fragments for an authenticated adapter. They are not standalone HTTP commands.

```json
{"fields": {"customfield_10028": 5}}
```

Story Points is numeric.

```json
{"fields": {"customfield_10795": {"value": "M"}}}
```

Size is a select value: `XS`, `S`, `M`, `L`, or `XL`.

```json
{"fields": {"customfield_10001": {"id": "TEAM_ID"}}}
```

Team uses an Atlassian team ID. Discover it from an existing issue through the authenticated
adapter; never guess it.

```json
{"fields": {"customfield_10785": {"value": "Enhancement"}}}
```

Release Note Type is a select value. Allowed values include `Feature`, `Enhancement`,
`Developer Preview`, `Deprecated Functionality`, `Removed Functionality`, and
`Release Note Not Required`.

## Write boundary

A REST-backed write is an external write, so the skill that owns the verb invokes
`/mutation-gate` and follows it. Two details are specific to REST here: the operation's
preview is the full JSON payload rather than a command line, and the outcome is read back from the
changed fields rather than taken from the response, because a request the API accepts can still
leave a field unset.

## Response handling

| Result | Action |
|---|---|
| Validation failure | Re-read field metadata, correct the payload, and re-confirm if it changed |
| Unauthenticated | Name `/setup-rhdh-skills atlassian-mcp`; do not inspect or repair credentials here |
| Forbidden | Report the missing permission; do not retry with another identity |
| Not found | Verify the issue key before retrying |
| Rate limited | Honor the adapter retry delay and retry once |

REST search is not a fallback for bulk JQL in this skill. Use `acli --paginate` or the authenticated
GraphQL adapter instead.

## Greenhopper sprint report and burndown

These endpoints power the board UI at
`https://redhat.atlassian.net/jira/software/c/projects/RHIDP/boards/{boardId}/reports/burndown-chart?sprint={sprintId}`.
They are **not** a public Jira Cloud API. `acli` has no equivalent. Treat them as
best-effort and unstable: Cloud may 404 or 403 them, and the JSON may drift.

Capability gate, in addition to the seam rules above:

1. Prefer `acli` for search, sprint view, and enrich. Greenhopper is REST because
   there is no `acli` verb.
2. Run `uv run scripts/setup.py --json`. If `token_file_found` is false or
   `token_file_status` is not `valid`, skip Greenhopper in one line and
   reconstruct. Do not print file contents. Do not `chmod 644` the token.
3. Fetch through the bundled adapter:

```bash
uv run scripts/greenhopper.py sprintreport --board BOARD_ID --sprint SPRINT_ID
```

4. Never `curl`, never an Authorization header in chat, never a credential in
   context. The adapter may read `email:token` from the file next to the real
   `acli` binary, or from `JIRA_TOKEN_FILE`.
5. On 404, 403, or a body that lacks the keys below, skip in one line and
   reconstruct. Do not retry as raw REST.

```
GET /rest/greenhopper/1.0/rapid/charts/sprintreport?rapidViewId={boardId}&sprintId={sprintId}
GET /rest/greenhopper/1.0/rapid/charts/scopechangeburndownchart?rapidViewId={boardId}&sprintId={sprintId}
```

Callers should accept this shape and ignore unknown fields. Live keys from
`scripts/greenhopper.py sprintreport --board 11374 --sprint 68649` (200,
sprint 68649 / RHDH COPE 3295 CLOSED). The report object has `contents`,
`sprint`, `supportsPages`, and `lastUserToClose`. There is no top-level
`rapidViewId`. `contents` keys:

`completedIssues`, `issuesNotCompletedInCurrentSprint`, `puntedIssues`,
`issuesCompletedInAnotherSprint`, `issueKeysAddedDuringSprint`,
`completedIssuesEstimateSum`, `completedIssuesInitialEstimateSum`,
`issuesNotCompletedEstimateSum`, `issuesNotCompletedInitialEstimateSum`,
`allIssuesEstimateSum`, `puntedIssuesEstimateSum`,
`puntedIssuesInitialEstimateSum`,
`issuesCompletedInAnotherSprintEstimateSum`,
`issuesCompletedInAnotherSprintInitialEstimateSum`.

Issue rows use `key`, `statusName`, `estimateStatistic`, and
`currentEstimateStatistic` (`statFieldId` / `statFieldValue.value`). They do
not carry a `currentEstimate` scalar. Sum objects are `{value, text}`.
`issueKeysAddedDuringSprint` is `{issueKey: true}`.

```json
{
  "sprint": {
    "id": 68649,
    "name": "RHDH COPE 3295",
    "state": "CLOSED"
  },
  "contents": {
    "completedIssues": [
      {
        "key": "RHIDP-1001",
        "statusName": "Closed",
        "estimateStatistic": {
          "statFieldId": "customfield_10028",
          "statFieldValue": {"value": 5.0}
        },
        "currentEstimateStatistic": {
          "statFieldId": "customfield_10028",
          "statFieldValue": {"value": 5.0}
        }
      }
    ],
    "issuesNotCompletedInCurrentSprint": [],
    "puntedIssues": [],
    "issuesCompletedInAnotherSprint": [],
    "issueKeysAddedDuringSprint": {"RHIDP-1002": true},
    "completedIssuesEstimateSum": {"value": 5, "text": "5.0"},
    "completedIssuesInitialEstimateSum": {"value": 5, "text": "5.0"},
    "issuesNotCompletedEstimateSum": {"value": 0, "text": "0.0"},
    "issuesNotCompletedInitialEstimateSum": {"value": 0, "text": "0.0"},
    "allIssuesEstimateSum": {"value": 5, "text": "5.0"},
    "puntedIssuesEstimateSum": {"value": 0, "text": "0.0"},
    "puntedIssuesInitialEstimateSum": {"value": 0, "text": "0.0"},
    "issuesCompletedInAnotherSprintEstimateSum": {"value": 0, "text": "0.0"},
    "issuesCompletedInAnotherSprintInitialEstimateSum": {"value": 0, "text": "0.0"}
  }
}
```

`completedIssuesEstimateSum` is completed at sprint end.
`issuesNotCompletedEstimateSum` / `puntedIssuesEstimateSum` are not done.
`issuesCompletedInAnotherSprint` rolled forward and finished later — **not**
completed in this sprint. `issueKeysAddedDuringSprint` is the grey
scope-change on the burndown chart (interrupt). Committed at start is the
initial-estimate sums, or `allIssuesEstimateSum` minus added keys.

Prefer the sum fields when present; per-issue `statFieldValue` can be empty.

`/rhdh-release-capacity-plan` consumes this. It never copies these paths into
its own files.

### Reconstruction when Greenhopper is skipped

Same numbers the chart is drawn from, without the chart API — weaker, because
issues still listed on an old sprint that later Closed are counted again:

1. `acli jira sprint view --id SPRINT_ID --json` for `startDate`.
2. Paginated `acli` search with allowed `--fields` (`key,summary,status,issuetype,assignee`),
   then enrich story points and status with `parse_issues.py --enrich` or
   `view --fields '*all'`. Do not pass `storypoints` or `sprint` to search
   `--fields`; `acli` rejects them.
3. An issue is interrupt when changelog (or the Greenhopper added-keys set)
   shows its Sprint field joined after `startDate`. If changelog cannot be
   fetched, report interrupt as unretrieved — do not treat that as zero.
4. Completed is status Closed or Release Pending. Do not treat
   `issuesCompletedInAnotherSprint` as completed here.
5. Always include the human chart URL in the report so a person can open the
   same view.

