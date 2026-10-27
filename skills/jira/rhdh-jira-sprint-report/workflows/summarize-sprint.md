# Sprint review summary

Generate a sprint review summary: committed versus completed, per-member
breakdown, epic progress, demo checklist with naming conventions, and velocity
trend.

Reads go through `/rhdh-jira-api`; `/rhdh-jira-context` owns the JQL and the
board and sprint IDs. The optional local commands live behind
`/rhdh-jira-api`.

## Input

1. **Team ID** — the Jira team UUID. Ask if it was not given.
2. **Sprint** — defaults to the active sprint. Accepts `previous` for the last
   closed one, or a sprint name or ID.
3. **Board ID** — optional. Look it up in `/rhdh-jira-context` or ask.

## Step 1 — Resolve the sprint

List the board's active and most recent closed sprints; extract sprint ID,
name, start date, and end date.

> Local commands: `/rhdh-jira-api`

## Step 2 — Fetch every issue in the sprint

```jql
project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS) AND sprint = SPRINT_ID AND "Team[Team]" = TEAM_ID
```

> Local commands: `/rhdh-jira-api`

## Step 3 — Partition

| Category | Condition |
|---|---|
| **Completed** | Status is Closed or Release Pending |
| **Carried over** | Anything else — In Progress, To Do, Review |
| **Added mid-sprint** | The issue joined the sprint after the sprint start date |

Every issue lands in exactly one of the first two. Mid-sprint additions overlay
both.

## Step 4 — Committed versus completed

| Metric | Computation |
|---|---|
| Committed SP | Sum of story points across all sprint issues |
| Completed SP | Sum across completed issues only |
| Completion rate | `completed_sp / committed_sp × 100` |
| Scope creep | Count and points of mid-sprint additions |

Below 70%, flag it: "Below 70% completion — review sprint commitments." Above
100%, note that the team pulled in extra work.

## Step 5 — Per-member breakdown

Group by assignee: issues closed, points completed, issues carried over, points
carried over. Highlight the top contributor by points completed.

Anyone with zero completions may be blocked, on PTO, or doing work Jira does not
track. State the number; do not editorialize.

## Step 6 — Epic progress

Group completed work by parent Epic. For each Epic with at least one completed
child:

1. Count **all** children — `parent = {epic_key}` across every status — for the
   denominator.
2. Count children in Closed or Release Pending.
3. State "X/Y stories closed this sprint ({before}% → {after}% complete)".

## Step 7 — Demo checklist

Find issues carrying the `demo` label. For each:

1. Check whether the parent Feature in RHDHPLAN has a Feature Demo link set.
2. Generate the RHDH naming conventions:
   - Demo file: `${SPRINT_NUMBER} ${JIRA_Project}-${JIRA_NUMBER} ${DEMO_TITLE}`
   - Slide: `${SPRINT_NUMBER} ${Team name} Review`
3. Suggest a venue — Sprint Review for customer-facing features, Team Forum for
   team-related demos, Architecture Call for deep technical topics.

Flag a missing link: "Demo required but no Feature Demo link on the parent
Feature." That link is required at Release Pending.

## Step 8 — Velocity trend

List the board's last three closed sprints, then run the completed-points query
below per sprint.

> Local commands: `/rhdh-jira-api`

```jql
project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS)
  AND sprint = SPRINT_ID
  AND status in (Closed, "Release Pending")
  AND "Team[Team]" = TEAM_ID
```

Compare this sprint against the three-sprint average and give the trend.

## Step 9 — Save

Offer to save: "Save as markdown? [y/N]" If yes, write
`sprint-report-{team}-{sprint}-{YYYY-MM-DD}.md` in the current working directory,
or a path the user supplies. This is a local file, not a Jira write.

## Output

```markdown
## Sprint Report — {team} {sprint}

Period: {start} – {end}

### Summary
| Metric | Value |
|--------|-------|
| Committed | {committed_sp} SP ({committed_count} items) |
| Completed | {completed_sp} SP ({completed_count} items) |
| Carried over | {carried_sp} SP ({carried_count} items) |
| Added mid-sprint | {scope_count} items ({scope_sp} SP) |
| Completion rate | {rate}% |

### Per-Member
| Member | Closed | SP Done | Carried | SP Carry |
|--------|--------|---------|---------|----------|

*Jira-tracked work only — code review, docs, support, and meetings do not appear.*

### Epic Progress
| Epic | Summary | This Sprint | Overall |
|------|---------|-------------|---------|

### Demo Items
| # | Issue | Summary | Demo Link | File Name | Venue |
|---|-------|---------|-----------|-----------|-------|

**Slide name:** `{sprint_number} {team} Review`

### Velocity Trend
| Sprint | SP | vs Avg |
|--------|----|--------|
```

## Error handling

| Error | Action |
|---|---|
| No active or closed sprint found | "No sprint found for this board. Check the board ID." |
| Sprint has 0 issues | "Empty sprint. Was the work tracked elsewhere?" |
| Parent Epic query fails | Skip epic progress for that issue and say "parent unavailable" |
| `demo` label but no parent Feature | Note that the demo link cannot be checked |
| File save fails | Warn. The summary was already displayed. |

## Caveats

1. **Scope creep detection is approximate.** It checks whether the sprint
   assignment date is after the sprint start, so issues moved between sprints can
   show as false positives.
2. **Demo venue routing is a suggestion**, based on issue type and labels rather
   than a hard rule.
3. **Release Pending counts as completed.** Per team convention it stays in the
   sprint and counts as done for velocity.
