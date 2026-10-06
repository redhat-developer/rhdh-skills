# Prepare refinement

Produce a facilitator brief before a team's refinement ceremony. Fetch the
team's queue, resolve release milestones, then analyze every issue and present
what matters for the session.

Use `acli` for Jira reads. `/rhdh-jira-api` owns auth and field references.

## Input

1. **Team name** — ask if not provided. Look up the board ID:

   | Board | ID | Team |
   |-------|----|------|
   | RHDH Install | 11462 | Install |
   | RHDH Plugins | 11549 | Plugins |
   | RHDH Frontend Plugins & UI | 11525 | Frontend |
   | RHDH AI Sprint | 10725 | AI |
   | RHDH Cope | 11374 | COPE |
   | RHDH Documentation Sprint | 10851 | Documentation |

2. **Fix version** — e.g. `2.1.0`. Required.

## Step 1 — Resolve the team

Get the team UUID from one issue in the active sprint:

```bash
acli jira board list-sprints --id BOARD_ID --state active --json
acli jira sprint list-workitems --sprint SPRINT_ID --board BOARD_ID --limit 1 --json
acli jira workitem view ISSUE_KEY --fields "*all" --json
```

Read `customfield_10001.id` from the issue — that is the team UUID.

## Step 2 — Fetch the queue

```bash
acli jira workitem search \
  --jql 'project = RHIDP AND sprint in openSprints() AND "Team[Team]" = TEAM_ID AND status in (New, Refinement, "To Do") AND fixVersion = "VERSION"' \
  --fields "*all" --paginate --json
```

This gives you every issue the team needs to discuss for this version.

## Step 3 — Resolve release milestones

Fetch the RHDHPLAN release Feature for this version:

```bash
acli jira workitem search \
  --jql 'project = RHDHPLAN AND issuetype = Feature AND component = release AND status != Closed AND summary ~ "VERSION_LINE"' \
  --fields "summary,description" --json
```

Then `acli jira workitem view RHDHPLAN_KEY --fields description --json` and
parse the ADF milestone table for **feature freeze**, **code freeze**, and
**GA date**. `/rhdh-jira-api` has `adf_milestones.py` for this.

Determine which milestone window is active today:
- Before feature freeze → **Feature Freeze** window
- Between feature freeze and code freeze → **Code Freeze** window
- After code freeze → **GA** window

## Step 4 — Analyze each issue

For every issue in the queue, check:

| Check | How | Flag when |
|-------|-----|-----------|
| **Assignee** | `assignee` field | Missing — "unowned" |
| **Story Points** | `storyPoints` or `customfield_10028` | Missing — "unsized" |
| **Priority** | `priority.name` | "Undefined" — "no priority set" |
| **Epic children** | `acli jira workitem search --jql 'parent = KEY AND status != Closed' --count` | Epic with 0 children — "no breakdown" |
| **Status vs freeze** | issue status + days to freeze | New/Refinement close to freeze — "still in early state" |

For each issue, note what stands out. Do not just count — name the issue and
say what about it matters for this session.

## Step 5 — Present the brief

Structure the output as:

```
🎯 RHDH {Team} · Refinement

Release: {version}
{Milestone}: {date} · {days} days [🔥 if ≤ 14 days]

✨ Summary
{2-3 sentences: what the team should focus on, naming specific issues and
why they stand out. Mention the milestone window. Connect dots — e.g. an
unsized Epic with no children near code freeze is a bigger deal than a
Task missing priority.}

🚀 Feature Tracking
   {version} · {team}
   (Link: {dashboard URL or JQL link})

   ✨ {Per-issue observations for Epics/Features — name the key, say what's
      wrong, say why it matters for this session}

🎫 Team Queue
   {version} · {team}
   (Link: {dashboard URL or JQL link})

   ✨ {Per-issue observations for unowned, unsized, or noteworthy items —
      name the key, connect to other signals}

🧹 Hygiene
   {version} · {team}
   (Link: {dashboard URL or JQL link})

   ✨ {Items with missing fields. Name which fields, which issues.
      Call out any issue that appears in multiple sections above.}
```

### Dashboard links (Install team)

| Dashboard | URL |
|-----------|-----|
| Feature Tracking | https://redhat.atlassian.net/jira/dashboards/17955 |
| Team Refinement | https://redhat.atlassian.net/jira/dashboards/22332 |
| Hygiene | https://redhat.atlassian.net/jira/dashboards/23962 |

For other teams, link to the JQL query instead.

## Tone

Write like a facilitator prepping for the call — brief, specific, opinionated.
Name issues by key. Say what the team should discuss, not just what fields are
empty. If everything looks good, say so and keep it short.

## Helper script

`scripts/prepare_refinement.py` can fetch the queue and milestones in one call:

```bash
./scripts/prepare-refinement --team Install --fix-version 2.1.0 --facts-out /tmp/facts.json
```

It outputs structured facts JSON. You can use it to bootstrap the data, then
analyze and present the brief yourself. Or run the steps above manually.
