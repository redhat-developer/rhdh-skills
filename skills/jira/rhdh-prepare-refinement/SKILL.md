---
name: rhdh-prepare-refinement
description: >-
  Produces the facilitator brief before a team's refinement ceremony. The user
  says "prepare refinement for Install on 2.1.0" and gets a terse report:
  release milestones, queue analysis, per-issue observations, dashboard links.
  Works for any RHDH scrum team — Install, Plugins, Frontend, AI, COPE,
  Documentation. Use for "prepare refinement", "refinement prep", "what needs
  attention before refinement", or "refinement brief for [team] on [version]".
compatibility: "acli on PATH with a Jira session; Python 3.9+ and uv."
---

# Prepare RHDH refinement

## Route

Load `workflows/prepare-refinement.md`. It tells you what inputs to collect,
how to fetch the data, and how to present the analysis.

## Inputs

The agent needs two things from the user:

1. **Team** — e.g. "Install", "Plugins", "Frontend". Resolve the board ID from
   `/rhdh-jira-api` (references/jql-patterns.md, Boards table).
2. **Fix version** — e.g. "2.1.0". Scopes the queue JQL.

If the user says just "prepare refinement" without a team or version, ask.

## Boundary

- Deep per-issue readiness checks (exit criteria, duplicates, comments) are
  `/rhdh-jira-refine`.
- Building the next sprint from refined work is `/rhdh-jira-sprint-plan`.
- Opening new issues is `/rhdh-jira-create`.
- Release-wide status across all teams is `/rhdh-release-status`.
