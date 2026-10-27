---
name: rhdh-jira-api
description: >-
  Reads RHDH Jira and owns the mechanics every other RHDH Jira skill needs:
  JQL for RHIDP, RHDHPLAN, RHDHBUGS and RHDHSUPP, custom field IDs, GraphQL
  and REST fallbacks, board and sprint IDs, the component catalog, the
  workflow states with their exit criteria, and the local acli command
  reference with its traps. Use to look up an issue such as RHIDP-1234, to
  write or debug a JQL query, to answer "which field is Story Points", "why is
  my search returning 30 rows", or "what does Release Pending require".
  Reading and query mechanics only — deciding what to file, judging readiness,
  or changing an issue belongs to the Jira skill that owns that verb.
compatibility: "Authenticated read access to redhat.atlassian.net covering RHIDP, RHDHPLAN, RHDHBUGS and RHDHSUPP; ability to run a JQL search, read an issue with custom fields, and list boards and sprints. Windows, macOS, Linux."
local-tooling: "Optional: only for agents using the local CLI path — acli on PATH with a Jira session; Python 3.9+ and uv for the bundled scripts; an authenticated host Atlassian adapter for GraphQL and REST fallbacks. An agent with ADLC Jira tooling uses that instead. See references/tooling.md."
---

# RHDH Jira API

One home for talking to Jira. The query patterns, the field IDs, and the
workflow rules live here so that the create, refine, update, and sprint skills
carry none of their own copies.

This skill reads. It never decides what to file and never approves a write —
though it does define exactly what a write costs, because the payload shapes are
here.

## Goals, not tools

Every goal below states what it needs, never which tool to use. Use whichever
tool you actually have for Jira — an ADLC tool, the authenticated host
adapter, or, when you have the local CLIs, the commands in
[references/tooling.md](references/tooling.md). Prefer an ADLC tool over
wrapping a local CLI when both are available. The process — which query,
which fields, which rules — is the same either way.

All local command syntax, flags, traps, and script invocations live in
[references/tooling.md](references/tooling.md). Nothing in this file depends on
them.

## Route by question

| Question | Load |
|---|---|
| Is Jira reachable and authenticated? | [references/auth.md](references/auth.md) |
| What JQL answers this? Which board or sprint? | [references/jql-patterns.md](references/jql-patterns.md) |
| Which custom field, label, link type, component, or priority? | [references/fields.md](references/fields.md) |
| How do I create or query a private (Security Level) issue? | [references/fields.md](references/fields.md) (Private issues; also jql-patterns / tooling) |
| What must be true before this status transition? | [references/workflows.md](references/workflows.md) |
| I need a relationship-heavy bulk read or a team roster | [references/graphql-queries.md](references/graphql-queries.md) |
| The primary adapter cannot read or set this field | [references/rest-api-fallback.md](references/rest-api-fallback.md) |
| Sprint report or burndown-chart numbers | [references/rest-api-fallback.md](references/rest-api-fallback.md), then the Greenhopper sprint-report read — [references/tooling.md](references/tooling.md) locally |
| Which local command or flag does this, and what breaks? | [references/tooling.md](references/tooling.md) (local CLIs only) |

Load the one branch the question needs.

## The two read rules that produce wrong answers

Both fail silently, and both have burned this pack before. They apply to every
adapter, not only the local one.

**A bulk read must state whether it was truncated.** Result sets are paginated;
the default page is small (30 rows locally), and rows past it are dropped with
no warning — a query that should return 140 issues quietly returns 30 and every
count built on it is wrong. Fetch the full total before counting, and treat a
capped result as an incomplete answer, not a finding.

**A field you did not ask for comes back absent, not empty.** Default reads
return only assignee, issuetype, priority, status, and summary. Story Points,
Team, Size, and Sprint come back empty — which looks exactly like a field
nobody set. Re-read the issue with all fields before claiming any of them is
missing.

A field you could not retrieve is reported as unretrieved, never as empty.

> Tooling: `references/tooling.md#read-traps` — the exact local flags
> (`--limit`, `--paginate`, `--count`, `--fields '*all'`, `--enrich`) that
> enforce these rules in local mode. The bundled scripts, including
> `greenhopper.py`, are listed there too.

## Writes

This skill does not perform writes, but the payloads live here because the field
IDs do. It hands the caller a payload, never an effect. Whichever skill owns the
verb invokes `/mutation-gate` and executes it from there. In local mode the
caller may also receive the exact command from `references/tooling.md`.

Credentials never appear in an argument, a preview, a log, or the answer. A
command built here takes its credential from the authenticated adapter's own
store at run time — locally that is `acli`'s store or the in-process token-file
adapter, never printed — so nothing this skill hands back carries one.

## Boundary with the neighbouring skills

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

A read is complete when every field the answer asserts was actually fetched.
Report the exact JQL used, the number of issues returned, and whether the
result was truncated — a truncated result is an incomplete answer, not a
finding. Name the adapter that produced each fact. In local mode also report
the command. A field the API could not supply is named as unretrieved rather
than reported as empty or carried over from an earlier query.
