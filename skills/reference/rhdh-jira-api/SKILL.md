---
name: rhdh-jira-api
description: >-
  Reads RHDH Jira and owns the mechanics every other RHDH Jira skill needs:
  `acli` flags and their traps, JQL for RHIDP, RHDHPLAN, RHDHBUGS and RHDHSUPP,
  custom field IDs, GraphQL and REST fallbacks, board and sprint IDs, the
  component catalog, and the workflow states with their exit criteria. Use to
  look up an issue such as RHIDP-1234, to write or debug a JQL query, to answer
  "which field is Story Points", "why is my search returning 30 rows", or "what
  does Release Pending require". Reading and query mechanics only — deciding
  what to file, judging readiness, or changing an issue belongs to the Jira
  skill that owns that verb.
compatibility: "acli on PATH with a Jira session; Python 3.9+ and uv for the bundled scripts; an authenticated host Atlassian adapter for GraphQL and REST fallbacks. Windows, macOS, Linux."
---

# RHDH Jira API

One home for talking to Jira. The command syntax, the field IDs, the query
patterns, and the workflow rules live here so that the create, refine, update,
and sprint skills carry none of their own copies.

This skill reads. It never decides what to file and never approves a write —
though it does define exactly what a write costs, because the payload shapes are
here.

## Route by question

| Question | Load |
|---|---|
| Is Jira reachable? Is `acli` authenticated? | [references/auth.md](references/auth.md), then `uv run scripts/setup.py --json` |
| Which `acli` flag does this, and what breaks? | [references/acli-commands.md](references/acli-commands.md) |
| What JQL answers this? Which board or sprint? | [references/jql-patterns.md](references/jql-patterns.md) |
| Which custom field, label, link type, component, or priority? | [references/fields.md](references/fields.md) |
| What must be true before this status transition? | [references/workflows.md](references/workflows.md) |
| I need a relationship-heavy bulk read or a team roster | [references/graphql-queries.md](references/graphql-queries.md) |
| `acli` cannot read or set this field | [references/rest-api-fallback.md](references/rest-api-fallback.md) |
| Sprint report or burndown-chart numbers | [references/rest-api-fallback.md](references/rest-api-fallback.md), then `uv run scripts/greenhopper.py` |

Load the one branch the question needs.

## The two traps that produce wrong answers

Both fail silently, and both have burned this pack before.

**Default page size is 30.** Rows past the thirtieth are dropped with no
warning, so a query that should return 140 issues quietly returns 30 and every
count built on it is wrong. Pass `--limit 500` or `--paginate` on every bulk
search, and use `--count` first when the total matters.

**Custom fields are absent unless you ask for them.** `search --json` and
`view KEY --json` return only assignee, issuetype, priority, status, and
summary. Story Points, Team, Size, and Sprint come back empty — which looks
exactly like a field nobody set. Enrich with `scripts/parse_issues.py --enrich`
or `view KEY --fields '*all' --json` before claiming any of them is missing.

A field you could not retrieve is reported as unretrieved, never as empty.

## Bundled scripts

Run these from this skill's directory.

| Script | Purpose |
|---|---|
| `scripts/setup.py` | Capability and auth detection; `--json` reports `token_file_found` / `token_file_status` without printing file contents |
| `scripts/parse_issues.py` | Enrich, flatten, select, filter, or CSV-export `acli` JSON |
| `scripts/greenhopper.py` | GET Greenhopper sprintreport / scopechange using the local token file in-process |
| `scripts/validate_components.py` | Compare the documented component catalog against live Jira |
| `scripts/jira-wiki-to-adf.py` | Convert a filled wiki-markup template to ADF JSON |

Stdlib only. Another skill invokes `/rhdh-jira-api` by name and lets this skill
run them; it never reaches into this directory by path.

## Writes

This skill does not perform writes, but the payloads live here because the field
IDs do. It hands the caller a command or a payload, never an effect. Whichever
skill owns the verb invokes `/mutation-gate` and runs it from there.

Credentials never appear in an argument, a preview, a log, or the answer. A
command built here takes its credential from `acli`'s own store, the local
token-file adapter (in-process, never printed), or the authenticated host
adapter at run time, so nothing this skill hands back carries one.

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
Report the exact JQL or command used, the number of issues returned, and whether
the result was truncated — a truncated result is an incomplete answer, not a
finding. Say which adapter produced each fact, `acli` or the host adapter. A
field the API could not supply is named as unretrieved rather than reported as
empty or carried over from an earlier query.
