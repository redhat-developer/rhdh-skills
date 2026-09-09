# acli Jira Command Reference

Cheat sheet for `acli jira` commands. For full flag details, run `acli jira <subcommand> --help`.

## Key Syntax Rules

1. **`view` takes a positional arg.** Everything else uses `--key`.
2. **Always pass `--yes`** on mutating commands (`edit`, `transition`, `assign`, `link create`) to skip interactive prompts.
3. **Use `--json`** when you need fields beyond `key`, `summary`, `status`, `assignee`, `issuetype`, `priority`, `description`. The `--fields` flag rejects `components`, `sprint`, `labels`, `fixVersions`, `storypoints`, and `parent`. Custom fields such as Story Points (`customfield_10028`) and Sprint (`customfield_10020`) are not on that allowlist — search with allowed fields, then enrich with `view --fields '*all'` or `parse_issues.py --enrich`.
4. **Use `--csv`** for search results you want to pipe or parse.
5. **Use `--paginate`** to fetch all results beyond the default page size.

## Work Items

### Search

> ⚠️ **Default page size is 30 results.** Results beyond 30 are silently dropped with no warning. Always pass `--limit 500` or `--paginate` for bulk queries. Use `--count` first to verify the total matches before fetching.

```bash
# JQL search with field selection (always set --limit for bulk)
acli jira workitem search --jql "project = RHIDP AND status = 'In Progress'" --fields "key,summary,status,assignee" --limit 500

# JSON output for full field data
acli jira workitem search --jql "project = RHIDP" --limit 500 --json

# Count only (check total before fetching)
acli jira workitem search --jql "project = RHDHBUGS AND status not in (Closed)" --count

# CSV export
acli jira workitem search --jql "project = RHIDP" --fields "key,summary,status" --csv --limit 500

# Fetch all results (paginated)
acli jira workitem search --jql "project = RHIDP AND sprint in openSprints()" --paginate
```

### View

```bash
# View issue (positional arg — NOT --key)
acli jira workitem view RHIDP-123

# Specific fields
acli jira workitem view RHIDP-123 --fields "summary,description,status"

# All fields
acli jira workitem view RHIDP-123 --fields "*all"

# JSON for full data (components, sprint, custom fields)
acli jira workitem view RHIDP-123 --json

# Open in browser
acli jira workitem view RHIDP-123 --web
```

### Create

> ⚠️ **`create` does not accept `--priority`, `--component`, or `--yes`.** Those flags exist on
> `edit`, `transition`, and `assign` only; passing them to `create` fails with "unknown flag".
> Create the issue first, then set priority, components, size (`customfield_10795`), and parent
> link (`customfield_10018`) in one update through the authenticated adapter in
> [rest-api-fallback.md](rest-api-fallback.md).

```bash
# Basic creation
acli jira workitem create --project RHIDP --type Story --summary "Implement auth plugin" --description "As a user..." --assignee "@me"

# With labels
acli jira workitem create --project RHDHBUGS --type Bug --summary "Login fails" --label "RHDH-Customer,ci-fail"

# With parent (sub-task or child of epic)
acli jira workitem create --project RHIDP --type Task --summary "Write tests" --parent RHIDP-12968

# From JSON file (complex issues)
acli jira workitem create --from-json workitem.json --project RHIDP --type Epic

# Generate JSON template
acli jira workitem create --generate-json

# From description file
acli jira workitem create --project RHIDP --type Story --summary "New feature" --description-file story.txt
```

### Edit

```bash
# Edit summary (--key flag, NOT positional)
acli jira workitem edit --key RHIDP-123 --summary "Updated summary" --yes

# Edit multiple issues
acli jira workitem edit --key "RHIDP-123,RHIDP-124" --assignee "jdoe@example.com" --yes

# Edit by JQL (batch)
acli jira workitem edit --jql "project = RHIDP AND labels = 'needs-info'" --labels "needs-pm" --yes

# Add/remove labels
acli jira workitem edit --key RHIDP-123 --labels "demo,rhdh-testday" --yes
acli jira workitem edit --key RHIDP-123 --remove-labels "needs-info" --yes

# Edit description from file
acli jira workitem edit --key RHIDP-123 --description-file updated.txt --yes

# Edit issue type
acli jira workitem edit --key RHIDP-123 --type Task --yes
```

### Transition

```bash
# Move to status (--key flag)
acli jira workitem transition --key RHIDP-123 --status "In Progress" --yes

# Batch transition by JQL
acli jira workitem transition --jql "project = RHIDP AND status = 'Review'" --status "Closed" --yes

# Ignore errors on batch (some may not have valid transition)
acli jira workitem transition --jql "..." --status "To Do" --yes --ignore-errors
```

### Assign

```bash
# Assign to self
acli jira workitem assign --key RHIDP-123 --assignee "@me" --yes

# Assign to user
acli jira workitem assign --key RHIDP-123 --assignee "jdoe@example.com" --yes

# Assign to project default
acli jira workitem assign --key RHIDP-123 --assignee "default" --yes
```

### Comment

```bash
# Add comment
acli jira workitem comment create --key RHIDP-123 --body "Investigation complete. Root cause: ..."

# List comments
acli jira workitem comment list --key RHIDP-123

# Update comment
acli jira workitem comment update --key RHIDP-123 --id 12345 --body "Updated findings"

# Delete comment
acli jira workitem comment delete --key RHIDP-123 --id 12345
```

### Links

```bash
# List available link types
acli jira workitem link type

# Create link (--out = source, --in = target)
acli jira workitem link create --out RHIDP-123 --in RHIDP-456 --type "Blocks" --yes

# List links on an issue
acli jira workitem link list --key RHIDP-123

# Delete link (by link ID only, no --key needed)
acli jira workitem link delete --id 12345 --yes
```

### Attachments

```bash
# List attachments (note: attachment upload is not available via acli)
acli jira workitem attachment list --key RHIDP-123

# Delete attachment
acli jira workitem attachment delete --key RHIDP-123 --id 12345
```

## Boards

```bash
# Search boards by project
acli jira board search --project RHIDP

# Search by name
acli jira board search --name "RHDH Cope"

# Get board details
acli jira board get --id 11374

# List sprints for a board (--id, NOT --board-id)
acli jira board list-sprints --id 11374

# Active sprints only
acli jira board list-sprints --id 11374 --state active
```

## Sprints

```bash
# View sprint details
acli jira sprint view --id 65456

# List work items in a sprint
acli jira sprint list-workitems --sprint 65456 --board 11374 --limit 500

# Create sprint
acli jira sprint create --name "RHDH COPE 3292" --board 11374
```

**Sprint JSON gotcha:** `list-workitems --json` returns `{"issues": [...], "maxResults": N, ...}` — NOT a flat array. Extract the `issues` array before piping to `parse_issues.py`:

```bash
acli jira sprint list-workitems --sprint 65456 --board 11374 --limit 500 --json | python -c "
import json, sys; json.dump(json.load(sys.stdin)['issues'], sys.stdout)
" | uv run scripts/parse_issues.py --enrich -s key,summary,status,story_points
```

## Projects

```bash
# List recent projects
acli jira project list --recent 10

# View project details
acli jira project view --key RHIDP
```

## Filters

```bash
# Search for saved filters
acli jira filter search --name "RHDH" --limit 500

# List my/favourite filters
acli jira filter list --my --limit 500
acli jira filter list --favourite --limit 500

# Get filter details (includes JQL)
acli jira filter get --id 10001
```

## Output Format Differences

| Behavior | Table (default) | `--json` |
|----------|----------------|----------|
| Description | Plain text | ADF (Atlassian Document Format) |
| Team field | String name | Complex object `{id, name, avatarUrl, ...}` |
| Sprint field | Not shown | Array of sprint objects |
| Components | Not available via `--fields` | Full objects |
| Labels | Not available via `--fields` | Array of strings |
| Fix versions | Not available via `--fields` | Array of version objects |

### Formatted descriptions need ADF

Jira Cloud's editor is ADF-native. Plain text and Jira wiki markup (`h1.`, `*bold*`) both render as
literal characters in the UI, so a description file written in wiki markup ships broken. Fill a wiki
markup template, convert it with `scripts/jira-wiki-to-adf.py <input.txt> <output.json>`, then pass
the result via `--description-file`. Both `create` and `edit` accept ADF JSON that way. When
reading, `--json` returns ADF too — don't try to round-trip it.

## Custom Fields and `--enrich`

**Critical:** Both `search --json` and `view KEY --json` (without `--fields "*all"`) return only basic fields: assignee, issuetype, priority, status, summary. Custom fields (story_points, team, sprint, size) are NOT included.

To get custom fields, you MUST either:

1. Use `view KEY --fields "*all" --json` (what `--enrich` does internally per issue), or
2. Use `parse_issues.py --enrich` (recommended — handles batching and flattening)

Without `--enrich`, custom fields appear as empty strings — making it look like data isn't set when it is. This is the #1 source of false "missing data" reports.
