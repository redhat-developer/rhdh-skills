---
name: rhdh-prepare-refinement
description: >-
  Intelligent refinement brief for RHDH scrum teams. Analyzes the queue,
  surfaces non-obvious risks (scope unclear, blockers, stale work, timeline
  unrealistic), identifies patterns, and makes recommendations about what to
  discuss. Say "prepare refinement for Install on 2.1.0" and get actionable
  insights, not field validation. Use for "prepare refinement", "refinement
  prep", or "what should we discuss in refinement for [team] on [version]".
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

## Boundary with the neighbouring skills

- Per-issue exit-criteria checks, duplicates, comments → `/rhdh-jira-refine`.
- Sprint planning from refined work → `/rhdh-jira-sprint-plan`.
- Opening new issues → `/rhdh-jira-create`.
- Release-wide status across all teams → `/rhdh-release-status`.

## Completion

Complete when the refinement brief is printed to the conversation with analyzed
issues, identified risks, and actionable recommendations. No files written, no
Jira state modified.
