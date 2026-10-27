# Local tooling: sprint-report commands

**The optional tooling sidecar.** Exact commands for the goals in `SKILL.md`,
for agents that have the local CLIs. An ADLC tool may serve the same goals;
postconditions stated in `SKILL.md` or `/rhdh-jira-api` bind whichever tool
executes.
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
