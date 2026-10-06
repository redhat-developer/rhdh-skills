# Prepare refinement

Produce a facilitator brief before a team's refinement ceremony. Fetch the
team's queue, resolve release milestones, analyze every issue, present what
matters for the session.

Use `acli` for all Jira reads. `/rhdh-jira-api` owns auth, field references,
JQL patterns, and the board/team table.

## Input

1. **Team name** — ask if not provided. Look up the board ID from
   `/rhdh-jira-api` references/jql-patterns.md:

   | Board | ID | Team |
   |-------|----|------|
   | RHDH Install | 11462 | Install |
   | RHDH Plugins | 11549 | Plugins |
   | RHDH Frontend Plugins & UI | 11525 | Frontend |
   | RHDH AI Sprint | 10725 | AI |
   | RHDH Cope | 11374 | COPE |
   | RHDH Documentation Sprint | 10851 | Documentation |

2. **Fix version** — e.g. `2.1.0`. Required.

## Step 1 — Resolve the team ID

Get the team UUID from one issue in the active sprint:

```bash
acli jira board list-sprints --id BOARD_ID --state active --json
acli jira sprint list-workitems --sprint SPRINT_ID --board BOARD_ID --limit 1 --json
acli jira workitem view ISSUE_KEY --fields "*all" --json
```

Read `customfield_10001.id` — that is the team UUID for JQL.

## Step 2 — Fetch the queue

```bash
acli jira workitem search \
  --jql 'project = RHIDP AND sprint in openSprints() AND "Team[Team]" = TEAM_ID AND status in (New, Refinement, "To Do") AND fixVersion = "VERSION"' \
  --fields "*all" --paginate --json
```

## Step 3 — Resolve release milestones

Find the RHDHPLAN release Feature for this version line:

```bash
acli jira workitem search \
  --jql 'project = RHDHPLAN AND issuetype = Feature AND component = release AND status != Closed' \
  --fields "summary,description" --json
```

Match the version line (e.g. "2.1") in the summary. Then fetch the full
description to parse the ADF milestone table:

```bash
acli jira workitem view RHDHPLAN_KEY --fields description --json
```

Extract **feature freeze**, **code freeze**, **GA date** from the ADF table
rows. `/rhdh-jira-api` has `adf_milestones.py` for parsing — or read the
date nodes directly from the JSON (type `date`, timestamp in
`attrs.timestamp`).

Determine the active milestone window:
- Today ≤ feature freeze → **Feature Freeze** window
- Feature freeze < today ≤ code freeze → **Code Freeze** window
- After code freeze → **GA** window

## Step 4 — Deep analysis

For each issue, gather context beyond basic fields:

```bash
acli jira workitem view ISSUE_KEY --json | jq '{
  key, summary, status: .fields.status.name,
  assignee: .fields.assignee.displayName // "Unassigned",
  issuetype: .fields.issuetype.name,
  created: .fields.created,
  description: .fields.description,
  links: .fields.issuelinks,
  labels: .fields.labels,
  components: .fields.components
}'

# For Epics, check children
acli jira workitem search --jql 'parent = KEY AND status != Closed' --count

# Get recent comments (last 30 days signals active discussion or blockers)
acli jira workitem view ISSUE_KEY --comments --json | jq '.fields.comment.comments[-3:]'
```

Look for:
- **Scope clarity**: Empty Epics, vague descriptions, "TBD" language
- **Staleness**: Created >90 days ago but still in New/To Do
- **Blockers**: Linked "blocked by" issues, comments mentioning blockers
- **Cross-team deps**: Links to other team's boards, external components
- **Related work clusters**: Multiple issues about same component (e.g., 3 must-gather items)

## Step 5 — Risk patterns and recommendations

Synthesize findings into actionable insights:

1. **Timeline reality check**: Given days to code freeze and unsized queue, what's realistic?
2. **Scope questions**: Which Epics/issues have unclear scope that needs discussion?
3. **Blockers**: What's blocked or waiting on other work?
4. **Grouping opportunities**: Should related items be consolidated or tracked as Epic?
5. **Stale work**: Has anything been sitting untouched? Should it be descoped?
6. **Assignment gaps**: Which unassigned items need owners vs. which can wait?

Connect the dots — don't just list missing fields.

## Step 6 — Present actionable insights

**CRITICAL**: Every issue mentioned anywhere must have an inline link.

Issue link format: `[RHIDP-XXXX](https://redhat.atlassian.net/browse/RHIDP-XXXX)`

```
🎯 RHDH {Team} · Refinement Brief

Release: {version}
{Milestone label}: {date} · {days} days [🔥 if ≤ 14 days]

## 🔥 What to discuss

{Numbered priority list, top-to-bottom. Link EVERY issue EVERY time it's mentioned:}

1. **[RHIDP-XXXX](https://redhat.atlassian.net/browse/RHIDP-XXXX)** — {Why it matters}: {Specific observation}. → **Do this**: {Action with links if mentioning other issues}

2. **Must-gather cluster** — [RHIDP-A](link), [RHIDP-B](link), [RHIDP-C](link): {Age, assignment, why clustered}. → **Do this**: Descope [RHIDP-A](link), [RHIDP-B](link) to 2.2.0; keep [RHIDP-C](link)

3. **Timeline reality** — [RHIDP-X](link), [RHIDP-Y](link), [RHIDP-Z](link) all 90+ days old, 7 days to freeze. → **Do this**: Move [RHIDP-X](link), [RHIDP-Y](link) to 2.2.0; focus on [RHIDP-Z](link)

{If blockers exist:}
4. **[RHIDP-YYYY](link)** blocked by [RHIDP-ZZZZ](link) — {Impact}. → **Do this**: Escalate or descope

---

**Dashboards**
- [Team refinement queue](https://redhat.atlassian.net/jira/dashboards/22332)
- [Feature tracking](https://redhat.atlassian.net/jira/dashboards/17955)
- [Hygiene](https://redhat.atlassian.net/jira/dashboards/23962)
- [Release plan: RHDH {version}](https://redhat.atlassian.net/browse/RHDHPLAN-{KEY})
```

## Tone

Write like a facilitator who did the homework so the team doesn't have to.

- **Surface insights**, not field validation. "RHIDP-17196 created 60 days ago, no Epic children, suggests scope unclear" beats "missing story points".
- **Connect dots**. Three must-gather items unassigned → recommend consolidation or single owner.
- **Be opinionated**. Given 7 days to code freeze, say what should be descoped.
- **Name real risks**. Blocked items, unclear scope, stale work, timeline crunches.
- **Skip noise**. Don't list every missing field — that's obvious from the dashboard.

If the queue is clean and realistic, say so in 2 sentences and stop.
