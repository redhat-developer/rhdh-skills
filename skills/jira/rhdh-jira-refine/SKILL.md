---
name: rhdh-jira-refine
description: >-
  Judges whether RHDH Jira work that already exists is ready to move forward —
  in RHIDP, RHDHPLAN, RHDHBUGS, and RHDHSUPP. Checks an issue, a JQL result, a
  sprint, or a backlog against the exit criteria for its status, then reports
  missing fields, hierarchy gaps, likely duplicates, unaddressed comments, stale
  work, and Feature Exploration readiness. Use for "is RHIDP-1234 ready",
  "refine this", "refine the backlog", "backlog hygiene", "what's missing on
  this epic", "run the Feature Exploration checklist", or "which of these are
  stale". Assesses existing work; it does not open new issues and does not build
  a sprint.
compatibility: "Authenticated read and write access to redhat.atlassian.net covering RHIDP, RHDHPLAN, RHDHBUGS and RHDHSUPP; ability to run a JQL search and read an issue with custom fields. Deliberately not gated on the grilling skill. Windows, macOS, Linux."
local-tooling: "Optional: a Jira session — acli, an Atlassian MCP server, or another tool."
---

# Refine RHDH Jira work

Answer "is this ready" with the criteria the RHDH workflow actually enforces,
and say what is missing rather than guessing at it.

## Goals, not tools

Every step below states its goal, never which tool to use. Use whichever tool
you actually have for Jira — an ADLC tool, an MCP server, or a CLI you know
how to drive. `/rhdh-jira-context` owns the JQL,
the field IDs, and the end-state rules that keep a silent failure from
becoming a false finding.

## Route

Load `workflows/refine-issues.md`. It covers both the per-issue readiness audit
and the Feature Exploration checklist — the same checks, applied at different
points in a Feature's life.

## Not gated on grilling

Unlike `/rhdh-jira-create`, this skill does **not** require the external
`grilling` skill and must not be blocked on it. Refinement reads work that
already exists. Gating it on an optional external skill would take a whole
capability offline for no benefit.

## Reads by default, writes only on request

The report is read-only. When the user asks for fixes, each change becomes an
external write: invoke `/mutation-gate` and follow it. A refine pass
typically proposes many small fixes at once, so state them as one set — issue key
and exact command per row — rather than approving them one at a time.

## Boundary with the neighbouring skills

- Opening new work is `/rhdh-jira-create`.
- Updating one known key — status, comment, assignee, link — is
  `/rhdh-jira-update`. Refinement reports across many issues; it does not
  replace that.
- Building the next sprint from the refined backlog is `/rhdh-jira-sprint-plan`.
- Pre-refinement ceremony brief with smart analysis is `/rhdh-prepare-refinement`.
- Exit criteria tables, field IDs, JQL, and the component catalog are
  `/rhdh-jira-context`.
- Sizing scales, duplicate detection, and decomposition rules are
  `/rhdh-jira-authoring`.
- What is still open against a release is `/rhdh-release-status`.

## Completion

Complete when every issue the report covers was actually fetched with its custom
fields enriched — an unenriched search returns empty Story Points, Team, Size,
and Sprint, which looks identical to a field nobody set and is the single most
common source of a false "missing data" finding. Report the JQL, the issue count,
and whether the result was truncated. Every finding names the check that produced
it and its severity. A field that could not be retrieved is reported as
unretrieved, never as missing.
