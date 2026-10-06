---
name: rhdh-prepare-refinement
description: >-
  Produces the facilitator brief before a team's refinement ceremony. The user
  says "prepare refinement for Install on 2.1.0" and gets a terse report with
  release milestones, per-issue observations, and dashboard links. Works for
  any RHDH scrum team. Use for "prepare refinement", "refinement prep", "what
  needs attention before refinement", or "refinement brief for [team] on
  [version]".
compatibility: "acli on PATH with a Jira session."
---

# Prepare RHDH refinement

## Route

Load `workflows/prepare-refinement.md`.

## Inputs

1. **Team** — e.g. "Install", "Plugins", "Frontend". Resolve the board ID
   from `/rhdh-jira-api` (references/jql-patterns.md, Boards table).
2. **Fix version** — e.g. "2.1.0". Scopes the queue.

If either is missing, ask.

## Boundary

- Per-issue exit-criteria checks, duplicates, comments → `/rhdh-jira-refine`.
- Sprint planning from refined work → `/rhdh-jira-sprint-plan`.
- Opening new issues → `/rhdh-jira-create`.
- Release-wide status across all teams → `/rhdh-release-status`.
