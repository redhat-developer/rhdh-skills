---
name: rhdh-jira-sprint-report
description: >-
  Summarizes an RHDH sprint that has finished or is finishing, from Jira RHIDP,
  RHDHPLAN, RHDHBUGS, and RHDHSUPP: committed versus completed story points,
  scope added mid-sprint, per-member breakdown, epic progress, the demo
  checklist with RHDH file and slide naming, and the velocity trend. Use for
  "sprint report", "what did we complete this sprint", "sprint review prep",
  "how did the sprint go", or "which demos do we owe". Looks back at work
  already done; preparing the sprint that has not started yet is a different
  job, and a single issue such as RHIDP-1234 is not a sprint.
compatibility: "Authenticated read access to redhat.atlassian.net covering RHIDP, RHDHPLAN, RHDHBUGS and RHDHSUPP; ability to run a JQL search and read sprints and boards. A Jira team ID and board ID. Windows, macOS, Linux."
local-tooling: "Reference implementation: acli on PATH with a Jira session; Python 3.9+ and uv for the bundled scripts. An ADLC integration may serve the same verbs only where it meets the postconditions /rhdh-jira-api pins. See references/tooling.md."
---

# Report on an RHDH sprint

Say what the sprint actually delivered, with the numbers traceable to a query.
Read-only.

## Verbs, not tool choices

Every Jira read this skill needs is a verb `/rhdh-jira-api` defines and pins —
board and sprint lookups, search — with exact inputs, outputs, and
postconditions. Invoke the verb; never improvise a raw Jira call. The bundled
scripts are the reference implementation, and
[references/tooling.md](references/tooling.md) holds this skill's invocations
of them. An ADLC integration may serve the same verbs only where it meets the
postconditions — a completion rate built on a silently truncated sprint fetch
is wrong, not approximate.

## Route

Load `workflows/summarize-sprint.md`. Run it at the end of a sprint, before the
review and demo meeting.

## Boundary with the neighbouring skills

- Preparing the sprint that has not started — carryover, capacity, ready queue —
  is `/rhdh-jira-sprint-plan`. This skill looks back; that one looks forward.
- Judging whether individual issues are in good shape is `/rhdh-jira-refine`.
- Board IDs, sprint naming, JQL, and custom field IDs are `/rhdh-jira-api`.
- Whether a team can fit `rhdh-X.Y-candidate` Features through Code Freeze is
  `/rhdh-release-capacity-plan`.
- Release-level readiness across sprints is `/rhdh-release-status`.

## Completion

Complete when committed and completed totals name the sprint and the JQL behind
them, the partition into completed, carried over, and added mid-sprint accounts
for every issue in the sprint, and epic progress states both the numerator and
the denominator. Report whether any search was truncated. The per-member
breakdown says out loud that it covers only Jira-tracked work — code review,
documentation, support, and meetings do not appear in it, and someone with zero
completions has not necessarily done nothing.
