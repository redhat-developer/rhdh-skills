---
name: rhdh-jira-api
description: >-
  How to interact with RHDH Jira when no native path is available: the local
  acli command reference with its traps (why a search returns 30 rows, which
  flags a command rejects, how to enrich custom fields), the REST and GraphQL
  fallbacks for what acli cannot read or set, auth and capability detection,
  and the bundled scripts — enrichment, the wiki-to-ADF converter, Greenhopper
  sprint reads, milestone parsing. Use for "how do I run this locally", "which
  command or flag", "set the field acli cannot set", or any read or write the
  caller must execute against Jira. Execution mechanics only — what a field
  is, which JQL answers a question, and what a status requires is
  /rhdh-jira-context.
compatibility: "Ability to reach redhat.atlassian.net covering RHIDP, RHDHPLAN, RHDHBUGS and RHDHSUPP through at least one path: an ADLC tool, the authenticated host adapter, or the local CLIs. Windows, macOS, Linux."
local-tooling: "Optional: acli on PATH with a Jira session; Python 3.9+ and uv for the bundled scripts; an authenticated host Atlassian adapter for GraphQL and REST fallbacks. See references/tooling.md."
---

# RHDH Jira API

The how of RHDH Jira: one home for executing reads and writes. What is being
asked for — field IDs, JQL, workflow states, exit criteria — lives in
`/rhdh-jira-context`; this skill turns it into calls and results.

## Goals, not tools

Every goal below states what it needs, never which tool to use. Use whichever
tool you actually have — an ADLC tool, the authenticated host adapter, or the
optional local commands in [references/tooling.md](references/tooling.md). The
end-state rules that keep a silent failure from becoming a wrong answer live
in `/rhdh-jira-context` and bind whichever tool executes.

All local command syntax, flags, traps, and script invocations live in
[references/tooling.md](references/tooling.md). Nothing in this file depends on
them.

## Route by question

| Question | Load |
|---|---|
| Is Jira reachable and authenticated? | [references/auth.md](references/auth.md) |
| The local command or flag for this, and what breaks | [references/tooling.md](references/tooling.md) — the optional sidecar |
| The primary adapter cannot read or set this field | [references/rest-api-fallback.md](references/rest-api-fallback.md) |
| A relationship-heavy bulk read or a team roster | [references/graphql-queries.md](references/graphql-queries.md) |
| Sprint report or burndown-chart numbers | [references/rest-api-fallback.md](references/rest-api-fallback.md), then the Greenhopper sprint-report read — [references/tooling.md](references/tooling.md) locally |

Load the one branch the question needs.

## Read traps

The two silent-failure rules — never report a truncated read as complete,
never report an unrequested field as empty — are stated and pinned in
`/rhdh-jira-context`. Locally they are enforced by flags:

> Local commands: [references/tooling.md](references/tooling.md#read-traps)

## Writes

This skill executes writes handed to it by the skill that owns the verb — it
never decides what to write. Whichever skill owns the write invokes
`/mutation-gate` and executes from here. The payloads live in
[references/rest-api-fallback.md](references/rest-api-fallback.md); the end
state every write must reach is pinned in `/rhdh-jira-context`.

Credentials never appear in an argument, a preview, a log, or the answer. A
command built here takes its credential from the authenticated adapter's own
store at run time — locally that is `acli`'s store or the in-process token-file
adapter, never printed — so nothing this skill hands back carries one.

## Boundary with the neighbouring skills

- What a field is, which JQL answers a question, and what a status requires is
  `/rhdh-jira-context`.
- Opening new work is `/rhdh-jira-create`.
- Judging whether existing work is ready is `/rhdh-jira-refine`.
- Changing a field, status, assignee, comment, or link on a known key is `/rhdh-jira-update`.
- Sprint carryover, velocity, and next-sprint capacity are `/rhdh-jira-sprint-plan`; the
  end-of-sprint summary is `/rhdh-jira-sprint-report`.
- Whether a team can fit `rhdh-X.Y-candidate` Features through Code Freeze is
  `/rhdh-release-capacity-plan`.
- Issue templates, the grill matrix, sizing scales, and decomposition rules are
  `/rhdh-jira-authoring`.
- What is still open against a release is `/rhdh-release-status`.
- Creating or repairing a credential is `/setup-rhdh-skills`.

## Completion

Complete when the caller received the result it asked for and can state where
every fact came from: name the adapter that produced it, and in local mode the
command. Report every operation that ran and every one that failed. When a
tool the sidecar assumes is missing from PATH, say so rather than improvising
an untested substitute — the goals and end-state rules are unchanged, only the
commands are tool-specific.
