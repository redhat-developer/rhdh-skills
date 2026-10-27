# Local tooling: sprint-report commands

**For agents that have the local CLIs.** This reference maps the sprint-report
workflow's reads to exact commands. Reach for it only when you actually have
`acli` — typically an agent working in a repository checkout. An agent with
ADLC Jira tooling should use that instead and ignore this file: an ADLC tool is
preferred over wrapping a CLI, and the report is the same either way.

`/rhdh-jira-api` owns the board and sprint IDs, the JQL, and the flag traps;
the commands below are the ones this workflow runs most.

## Sprints

```bash
acli jira board list-sprints --board BOARD_ID --state active --json
acli jira board list-sprints --board BOARD_ID --state closed --json --recent 3
```

Note `list-sprints` takes `--board`, while `board get` takes `--id`.

## Bulk read

The full-sprint fetch behind the partition and the per-sprint velocity sums:

```bash
acli jira workitem search \
  --jql 'project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS) AND sprint = SPRINT_ID AND "Team[Team]" = TEAM_ID' \
  --fields "key,summary,status,issuetype,priority,assignee,storypoints,parent,labels,sprint" --paginate --json
```

Always paginate — the default page is 30 rows and drops the rest silently, and
a truncated sprint silently skews every total built on it.

Epic-progress denominators run the same search with
`--jql "parent = EPIC_KEY"` across every status.
