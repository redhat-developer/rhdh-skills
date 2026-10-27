# Local tooling: sprint-plan commands

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
acli jira board list-sprints --board BOARD_ID --state future --json --recent 1
```

When the board ID itself is unknown:

```bash
acli jira board search --project RHIDP
```

Note `list-sprints` takes `--board`, while `board get` takes `--id`.

## Bulk read

Carryover, velocity, and the ready queue all run as JQL searches. Always
paginate — the default page is 30 rows and drops the rest silently:

```bash
acli jira workitem search \
  --jql 'project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS) AND sprint = SPRINT_ID AND status not in (Closed, "Release Pending") AND "Team[Team]" = TEAM_ID' \
  --fields "key,summary,status,assignee,storypoints,issuetype" --paginate --json
```

The velocity query is the same search with
`status in (Closed, "Release Pending")` and `--fields "key,storypoints"`.

When the `"Team[Team]"` JQL clause fails for a team, search without it and
post-filter on the team field. The post-filter is `/rhdh-jira-api`'s
`parse_issues.py` — invoke that skill by name to run it; never reach into its
directory by path. An in-process JSON filter before counting works too.
