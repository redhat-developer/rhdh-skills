# Sprint planning prep

Generate a sprint planning package: carryover report, velocity trend, per-member
capacity, ready-for-planning queue, and sprint fill suggestions.

Reads go through `/rhdh-jira-api`; `/rhdh-jira-context` owns the JQL and the
board and sprint IDs. The optional local commands live behind
`/rhdh-jira-api`.

## Input

1. **Team ID** — the Jira team UUID. Ask if it was not given; never infer a team
   from names.
2. **Board ID** — optional. Look it up in the board table in `/rhdh-jira-context`,
   or ask.
3. **Sprint** — optional. Defaults to planning the next one: the active sprint
   supplies carryover, the future sprint is the target.

## Step 1 — Resolve the sprint context

List the board's sprints by state: the active sprint (source of carryover), the
next sprint (planning target), and the last three closed sprints (source of
velocity).

> Local commands: `/rhdh-jira-api`

## Step 2 — Carryover

Issues in the active sprint that are not Closed or Release Pending:

```jql
project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS) AND sprint = SPRINT_ID AND status not in (Closed, "Release Pending") AND "Team[Team]" = TEAM_ID
```

> Local commands: `/rhdh-jira-api`

Flag any Epic in the sprint — only Bug, Task, and Story belong there: "RHIDP-1234
is an Epic. Epics should be broken into Stories or Tasks, not added to sprints."

Sum the carryover story points. If carryover exceeds average velocity, say so:
the sprint is overcommitted before any new work goes in.

## Step 3 — Velocity

For each of the last three closed sprints, sum completed story points:

```jql
project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS) AND sprint = SPRINT_ID AND status in (Closed, "Release Pending") AND "Team[Team]" = TEAM_ID
```

> Local commands: `/rhdh-jira-api`

Report points per sprint, the three-sprint average, and the trend — accelerating,
stable, or decelerating.

## Step 4 — Per-member capacity

Fetch the roster through `/rhdh-jira-api` (the `GetTeamRoster` query), keeping
only `FULL_MEMBER` entries. For each member, report carryover items and points,
open issues, points already committed in the next sprint, and an overloaded flag
at 10 open issues or 21 story points.

## Step 5 — Ready-for-planning queue

```jql
project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS)
  AND "Team[Team]" = TEAM_ID
  AND status in (Backlog, "To Do")
  AND sprint not in (openSprints(), futureSprints())
  AND (cf[10028] is not EMPTY OR issuetype = Bug)
  AND issuetype in (Bug, Task, Story)
  ORDER BY priority ASC, created ASC
```

Rank by priority, then by parent epic priority. Include key, summary, priority,
story points, parent epic, and assignee if set.

## Step 6 — Available capacity

```
available_SP = avg_velocity - carryover_SP
```

If that is negative, say plainly there is no room for new work.

## Step 7 — Fill suggestions

For each issue in the ready queue up to `available_SP`, get an assignee
recommendation from `/rhdh-jira-update` — it owns roster expertise, capacity
scoring, and the overload rules. Invoke it by name; do not restate its formula
here and do not let it apply any assignment.

Frame the result honestly: "These are suggestions. Team members self-select
during planning."

## Step 8 — Critical customer bugs

```jql
project in (RHIDP, RHDHBUGS) AND priority in (Blocker, Critical) AND labels = "RHDH-Customer" AND "Team[Team]" = TEAM_ID AND status != Closed
```

Surface these separately: critical customer bugs are exempt from capacity
constraints and get worked immediately regardless of sprint load. Jira label
search is case-insensitive, so this query catches both spellings.

## Step 9 — Retro action items

```jql
project = RHIDP AND component = 'Continuous Improvement' AND "Team[Team]" = TEAM_ID AND status != Closed ORDER BY priority ASC
```

## Output

```markdown
## Sprint Planning — {team}

{active_sprint} → Planning {target_sprint}

### Carryover ({count} items, {sp} SP)
| # | Issue | Summary | Assignee | Status | SP | Days |
|---|-------|---------|----------|--------|----|------|

Carryover ({sp} SP) vs avg velocity ({avg} SP): {assessment}

### Velocity (last 3 sprints)
| Sprint | Completed SP | Trend |
|--------|-------------|-------|

Avg: {avg} SP | Trend: {trend}

### Capacity
| Member | Carryover | Open | SP Load | Status |
|--------|-----------|------|---------|--------|

### Available Capacity
Avg velocity {avg} SP − carryover {carry_sp} SP = **{available} SP available**

### Ready for Planning ({count} items, {total_sp} SP)
| # | Issue | P | Summary | SP | Parent Epic |
|---|-------|---|---------|----|-------------|

### Fill Suggestions
| # | Issue | Summary | Suggested Assignee | Rationale |
|---|-------|---------|-------------------|-----------|

*Suggestions only — team members self-select during planning.*

### Critical Customer Bugs (exempt from capacity)
| Issue | Summary | Priority | Assignee |

### Retro Action Items (Continuous Improvement)
| Issue | Summary | Status |
```

## Error handling

| Error | Action |
|---|---|
| Board ID not found | Ask. Look it up in the board table in `/rhdh-jira-context`. |
| No active sprint | "No active sprint found. Is the team between sprints?" |
| No closed sprints | Skip velocity and say "no historical data — velocity unavailable". |
| Bulk search fails | Retry the paginated search once through the same adapter. Do not fall back to raw REST search. |
| Carryover query returns 0 | "Clean sprint — no carryover. Full velocity available." |

## Caveats

1. **Velocity is story-point based.** Inconsistent estimation makes the trend
   noisy. If story-point coverage is under 50%, fall back to issue count and say
   which you used.
2. **Bugs without points still show.** The convention is that every item needs
   points or a time-box; bugs in the ready queue without points appear, flagged.
3. **Release Pending stays in the sprint.** Per team convention it remains in the
   sprint and counts toward capacity.
4. **Team is not JQL-filterable in every context.** `/rhdh-jira-context` covers
   the `"Team[Team]"` syntax and its limits; the post-filter for cases where it
   fails is `/rhdh-jira-api`'s, run locally.
