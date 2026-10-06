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

## Step 4 — Analyze each issue

For every issue in the queue:

| Check | How | Flag when |
|-------|-----|-----------|
| Assignee | `assignee` field | Missing |
| Story Points | `storyPoints` or `customfield_10028` | Missing |
| Priority | `priority.name` | "Undefined" |
| Epic children | `acli jira workitem search --jql 'parent = KEY AND status != Closed' --count` | 0 children |
| Status vs freeze | status + days to freeze | New/Refinement with ≤ 14 days to freeze |

Name each issue by key. Say what specifically stands out. Connect the dots —
an unsized Epic with no children 7 days from code freeze is a bigger deal than
a Task missing priority.

## Step 5 — Present the brief

```
🎯 RHDH {Team} · Refinement

Release: {version}
{Milestone label}: {date} · {days} days [🔥 if ≤ 14 days]

✨ Summary
{2-3 sentences naming specific issues: why they matter, what the team
should discuss. Mention the milestone window. Be opinionated.}

🚀 Feature Tracking
   {version} · {team}
   (Link: {dashboard or JQL URL})

   ✨ {Per-issue: RHIDP-XXXX — what's wrong, why it matters now}

🎫 Team Queue
   {version} · {team}
   (Link: {dashboard or JQL URL})

   ✨ {Per-issue: unowned, unsized, or noteworthy — name the key}

🧹 Hygiene
   {version} · {team}
   (Link: {dashboard or JQL URL})

   ✨ {Items with missing fields. Name which issues, which fields.
      Call out any issue that also appeared above.}
```

### Install team dashboards

| Dashboard | URL |
|-----------|-----|
| Feature Tracking | https://redhat.atlassian.net/jira/dashboards/17955 |
| Team Refinement | https://redhat.atlassian.net/jira/dashboards/22332 |
| Hygiene | https://redhat.atlassian.net/jira/dashboards/23962 |

For other teams, use a Jira JQL search URL instead.

## Tone

Write like a facilitator prepping for the call — brief, specific, opinionated.
Name issues by key. Say what the team should discuss, not just what fields are
empty. If everything looks good, say so and keep it short.
