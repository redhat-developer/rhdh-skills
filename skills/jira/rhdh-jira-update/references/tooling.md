# Local tooling: update and assign commands

**For agents that have the local CLIs.** This reference maps the update
workflows' reads and writes to exact commands. Reach for it only when you
actually have `acli` — typically an agent working in a repository checkout. An
agent with ADLC Jira tooling should use that instead and ignore this file: an
ADLC tool is preferred over wrapping a CLI, and the change is the same either
way.

`/rhdh-jira-api` owns the field IDs, the JQL, and the flag traps; the commands
below are the ones these workflows run most.

## Issue detection

Step 1 of the update workflow probes local repository context, best-effort and
stopping at the first hit:

```bash
git branch --show-current 2>/dev/null | grep -oE '(RHIDP|RHDHPLAN|RHDHBUGS|RHDHSUPP)-[0-9]+'
gh pr view --json title,body 2>/dev/null
git log --oneline -10 2>/dev/null | grep -oE '(RHIDP|RHDHPLAN|RHDHBUGS|RHDHSUPP)-[0-9]+'
```

## Read

```bash
acli jira workitem view ISSUE_KEY --json
acli jira workitem view ISSUE_KEY --fields "*all" --json   # when custom fields matter
```

## Comment

```bash
acli jira workitem comment create --key ISSUE_KEY --body "comment text"
```

## Transition

```bash
acli jira workitem transition --key ISSUE_KEY --status "TARGET" --yes
```

Always pass `--yes` on mutating commands; they hang on interactive prompts
without it.

## Link

```bash
acli jira workitem link create --out ISSUE_KEY --in TARGET_KEY --type "Blocks" --yes
```

Remote (web) links are not issue links and `acli` cannot create one — use the
remote-link operation in `/rhdh-jira-api`.

## Bulk read

The assign workflow's recent-work and sprint-load queries:

```bash
acli jira workitem search \
  --jql "project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS) AND assignee = ACCOUNT_ID AND updated >= -90d ORDER BY updated DESC" \
  --fields "key,summary,status,issuetype,components" --limit 50 --json
```

The sprint-load query is the same search with
`sprint in (openSprints(), futureSprints()) AND status != Closed`, `--paginate`,
and `--fields "key,summary,status,storypoints,sprint,parent,components"`.

## Assign

```bash
acli jira workitem assign --key RHIDP-1234 --assignee "ACCOUNT_ID" --yes
```

`assign` takes `--key`, not a positional issue key, and hangs on an interactive
prompt without `--yes`. `/rhdh-jira-api` covers both, plus the flag differences
between `assign`, `edit`, and `transition`. For a batch, use the supported
`--from-file` form and show the complete file content for approval.
