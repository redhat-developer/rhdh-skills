# Reference implementation: refine-issue commands

**The reference implementation of the verbs `/rhdh-jira-api` pins.** These
commands are what run locally, and they are the behavior any other backend
must reproduce: same inputs, same outputs, same postconditions. An ADLC
integration may replace them only where it meets those postconditions —
otherwise these commands are the solution, not a suggestion.

`/rhdh-jira-api` owns the JQL patterns, the field IDs, and the flag traps; the
commands below are the ones this workflow runs most.

## Bulk read

Every check needs enriched issues — a plain search omits all custom fields, so
Story Points, Team, Size, and Sprint come back empty whether or not they are
set:

```bash
acli jira workitem search --jql "JQL_HERE" --fields "*all" --paginate --json
```

Pass `--limit 500` or `--paginate` on every bulk query: the default page is 30
rows and drops the rest silently. Use `--count` first when the total matters.

## Hierarchy lookups

Cross-project `parent =` queries are unreliable through GraphQL and REST
search; use the local search path for them:

```bash
acli jira workitem search --jql "parent = RHIDP-123 AND status != Closed" \
  --fields "key,summary,status,issuetype" --paginate --json
```

## Comments

```bash
acli jira workitem view ISSUE_KEY --fields "comment" --json
```

A 403 here means comments are not accessible — skip Check 4 for that issue and
say so.

## Writes

Remediation runs as one approved set through `/mutation-gate`. Per row:

```bash
acli jira workitem edit --key RHIDP-123 --priority "Major" --yes
acli jira workitem transition --key RHIDP-123 --status "Closed" --yes
acli jira workitem comment create --key RHIDP-123 --body "Closing as stale — ..."
```

Closing also needs the resolution field — set it through the authenticated
host adapter in `/rhdh-jira-api` when the local CLI cannot carry it.
