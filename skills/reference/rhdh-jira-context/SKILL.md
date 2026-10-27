---
name: rhdh-jira-context
description: >-
  Owns what RHDH Jira work is made of, independent of any tool: the custom
  field IDs (which field is Story Points), JQL patterns for RHIDP, RHDHPLAN,
  RHDHBUGS and RHDHSUPP, the workflow states with their exit criteria (what
  Release Pending requires), the component catalog, board and sprint IDs, the
  private-issue and customer-identity rules, and the read and write end-state
  rules that keep a silent failure from becoming a wrong answer. Use to answer
  "what is this field", "which JQL answers this", "what does this status
  require", or "which components exist". Knowledge only — running a query or
  making a change against Jira is /rhdh-jira-api.
compatibility: "None. Pure reference: no access, no tools, no writes."
---

# RHDH Jira context

The what of RHDH Jira: fields, JQL, workflow states, components, boards. One
home so the create, refine, update, and sprint skills carry none of their own
copies. This skill is knowledge — it names no commands and runs nothing. How
to execute any of it against Jira — the local commands, the REST and GraphQL
fallbacks, auth — is `/rhdh-jira-api`.

## Route by question

| Question | Load |
|---|---|
| What JQL answers this? Which board or sprint? | [references/jql-patterns.md](references/jql-patterns.md) |
| Which custom field, label, link type, component, or priority? | [references/fields.md](references/fields.md) |
| How do private (Security Level) issues work? | [references/fields.md](references/fields.md) (Private issues) |
| What must be true before this status transition? | [references/workflows.md](references/workflows.md) |

Load the one branch the question needs.

## The two read rules that produce wrong answers

Both fail silently, and both have burned this pack before. They apply to every
tool.

**A bulk read must state whether it was truncated.** Result sets are paginated,
and rows past a page are dropped with no warning — a query that should return
140 issues quietly returns 30 and every count built on it is wrong. Fetch the
full total before counting, and treat a capped result as an incomplete answer,
not a finding.

**A field you did not ask for comes back absent, not empty.** Default reads
return only a few basic fields. Story Points, Team, Size, and Sprint come back
empty — which looks exactly like a field nobody set. Re-read the issue with all
fields before claiming any of them is missing.

A field you could not retrieve is reported as unretrieved, never as empty.

## Boundary with the neighbouring skills

- Running a query, making a change, authenticating — the how — is `/rhdh-jira-api`.
- Opening new work is `/rhdh-jira-create`.
- Judging whether existing work is ready is `/rhdh-jira-refine`.
- Changing a field, status, assignee, comment, or link on a known key is `/rhdh-jira-update`.
- Sprint carryover, velocity, and next-sprint capacity are `/rhdh-jira-sprint-plan`; the
  end-of-sprint summary is `/rhdh-jira-sprint-report`.
- Issue templates, the grill matrix, sizing scales, and decomposition rules are
  `/rhdh-jira-authoring`.

## Completion

A read is complete when every field the answer asserts was actually fetched.
Report the exact JQL used, the number of issues returned, and whether the
result was truncated — a truncated result is an incomplete answer, not a
finding. A field the API could not supply is named as unretrieved rather than
reported as empty or carried over from an earlier query.

A write is complete when the issue was read back after the change and every
claimed field verified: a private issue was private from the moment of
create, what create could not carry landed in one follow-up update, and a
close carries both a resolution and a rationale comment.
