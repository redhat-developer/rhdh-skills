# Local tooling: create-issue commands

**For agents that have the local CLIs.** This reference maps the create
workflow's goals to exact commands. Reach for it only when you actually have
`acli` — typically an agent working in a repository checkout. An agent with
ADLC Jira tooling should use that instead and ignore this file: an ADLC tool is
preferred over wrapping a CLI, and the process — which type, which project,
which fields, which gates — is the same either way.

`/rhdh-jira-api` owns the field IDs, the component catalog, and the general
`acli` flag traps. What follows is only what the create workflow needs.

## Search

The sibling-awareness and Feature-Request lookups in the workflow run as JQL
searches. Always paginate — the default page is 30 rows and drops the rest
silently:

```bash
acli jira workitem search \
  --jql "parent = FEATURE-KEY AND issuetype = Epic AND status != Closed" \
  --fields "key,summary,status" --paginate --json
```

## Review file

Step 6 renders the pre-create review as a temporary markdown file. Any portable
temp mechanism works; on POSIX:

```bash
REVIEW=$(mktemp "${TMPDIR:-/tmp}/jira-review.XXXXXX.md")
```

On Windows use `%TEMP%` or Python `tempfile`. Fill the file with the review
structure the workflow defines, then hand the path to the user.

## Create

`create` does **not** accept `--priority`, `--component`, `--yes`,
`--version` / Affects Version, or `--security` flags; passing unknown flags
fails. For most **public** types, create with `--description-file` (ADF from
`/rhdh-jira-api`), then set the rest.

```bash
# Feature
acli jira workitem create --project RHDHPLAN --type Feature \
  --summary "Feature summary" --description-file "$ISSUE_ADF" \
  --assignee "ACCOUNT_ID" --label "rhdh-2.1-candidate"

# Epic / Story (same shape, --type and --project differ)
acli jira workitem create --project RHIDP --type Story \
  --summary "Story summary" --description-file "$ISSUE_ADF" --assignee "ACCOUNT_ID"

# Spike
acli jira workitem create --project RHIDP --type Task \
  --summary "SPIKE: Research multi-source catalog merging" \
  --description-file "$ISSUE_ADF" --assignee "ACCOUNT_ID"
```

**RHDHBUGS Bug:** Affects Version must be on the create call. Use a single
`--from-json` file that embeds both `versions` and the ADF `description` — do
**not** also pass `--description-file` on that create. Scaffold with
`acli jira workitem create --generate-json`, or create through the Atlassian
MCP with Affects Version / `versions` set.

```json
{
  "projectKey": "RHDHBUGS",
  "type": "Bug",
  "summary": "Bug summary",
  "description": { "type": "doc", "version": 1, "content": [] },
  "additionalAttributes": {
    "versions": [{ "name": "1.10.0" }],
    "components": [{ "name": "Actions" }]
  }
}
```

**Private issue (RHIDP / RHDHPLAN / RHDHBUGS):** put `security` on the create
call — `--from-json` (`additionalAttributes.security`) or MCP `createJiraIssue`
(`additional_fields.security`). On RHDHBUGS include `versions` in the same
create. Never create-then-restrict. Verify with
`acli jira workitem view KEY --fields '*all' --json` (defaults omit
`security`):

```json
{
  "projectKey": "RHIDP",
  "type": "Story",
  "summary": "Private summary",
  "description": { "type": "doc", "version": 1, "content": [] },
  "additionalAttributes": {
    "security": { "name": "Red Hat Employee" }
  }
}
```

The Atlassian MCP path needs no wiki→ADF conversion: pass
`contentFormat: markdown` and skip the converter.

**Post-create field update** (priority, components, size, points — one update
through `/rhdh-jira-api`'s REST adapter):

```bash
acli jira workitem edit --key RHIDP-XXX --priority "Major" --yes
```

## Comment

```bash
acli jira workitem comment create --key RHIDP-XXX --body "comment text"
```

## Support-case links

The RHDHSUPP → RHDHBUGS and RHDHSUPP → RHDHPLAN flows in
[support-intake.md](support-intake.md):

```bash
# RHDHBUGS Bug create: single --from-json (versions + ADF description inside)
acli jira workitem create --from-json "$BUG_CREATE_JSON"

# RHDHPLAN Feature Request create
acli jira workitem create --project RHDHPLAN --type "Feature Request" \
  --summary "Support OIDC token refresh in admin console" \
  --description-file "$FEATURE_ADF"

# Link either one to the support case, then comment on the RHDHSUPP issue
acli jira workitem link create --out RHDHSUPP-456 --in RHDHBUGS-789 --type "Related" --yes
acli jira workitem comment create --key RHDHSUPP-456 \
  --body "Defect captured in RHDHBUGS-789. Fix targeted for next y-stream release."
```
