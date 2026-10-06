---
name: rhdh-prepare-refinement
description: >-
  Produces the facilitator brief before a team's refinement ceremony. The user
  says "prepare refinement for Install on 2.1.0" and gets a terse report:
  release milestones, queue signals, dashboard links. Works for any RHDH scrum
  team — Install, Plugins, Frontend, AI, COPE, Documentation. Use for "prepare
  refinement", "refinement prep", "what needs attention before refinement", or
  "refinement brief for [team] on [version]".
compatibility: "acli on PATH with a Jira session; Python 3.9+ and uv."
---

# Prepare RHDH refinement

## Route

Load `workflows/prepare-refinement.md`. It tells you what inputs to collect and
how to run the script.

## Inputs

The agent needs two things from the user:

1. **Team** — e.g. "Install", "Plugins", "Frontend". The agent resolves the
   board ID from `/rhdh-jira-api` (references/jql-patterns.md, Boards table).
2. **Fix version** — e.g. "2.1.0". Scopes the queue JQL.

If the user says just "prepare refinement" without a team or version, ask.

## What it does

1. Fetches the team's open-sprint queue from Jira.
2. Resolves release milestones (feature freeze, code freeze, GA) from the
   RHDHPLAN release Feature ADF descriptions — same source all release skills use.
3. Evaluates signals: unassigned, unsized, missing priority, Epics without children.
4. Prints the brief: header → ✨ Summary → three dashboard sections with standouts.

## Boundary

- Deep per-issue readiness checks are `/rhdh-jira-refine`.
- Building the next sprint from refined work is `/rhdh-jira-sprint-plan`.
- Opening new issues is `/rhdh-jira-create`.
- Release-wide status is `/rhdh-release-status`.
