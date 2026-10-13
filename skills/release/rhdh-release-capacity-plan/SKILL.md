---
name: rhdh-release-capacity-plan
description: >-
  Forecasts whether a named RHDH scrum team can take the rhdh-X.Y-candidate
  Features for a release from Jira RHIDP, RHDHPLAN, RHDHBUGS, and RHDHSUPP:
  three-week remaining sprints through Code Freeze, PTO from the shared
  calendar, sample-sprint velocity with interrupt reserved rather than filled,
  Epic-first demand with a placeholder T-shirt→Fibonacci map when children
  have no story points, and two capacity ledgers — fillable planned-work
  versus theoretical availability after meetings and interrupt. Use for
  "capacity for the 2.2 release", "can Plugins fit these 2.2 candidates",
  "release capacity plan", "how much interrupt into 2.1 planning", or "will
  COPE have room for 1.10 candidates". A whole-release horizon for one team —
  not filling the next sprint, and not whether the release is ready to ship.
compatibility: "acli on PATH with a Jira session; Python 3.9+ and uv; a Jira team ID and board ID; gog for the team mapping, release schedule, and shared PTO calendar. Greenhopper sprint reports use the /rhdh-jira-api token-file adapter when the local .jira-token file is readable."
---

# Plan RHDH release capacity

Say whether a team can take the candidate Features for a named release, with
both ledgers and the arithmetic that produced them. Read-only.

## Route

Load `workflows/plan-capacity.md`. Run it when a team is choosing which
`rhdh-X.Y-candidate` Features to take for a release.

## Boundary with the neighbouring skills

- Filling **the next sprint** — carryover, three-sprint velocity, ready queue —
  is `/rhdh-jira-sprint-plan`. This skill looks across remaining sprints to Code
  Freeze.
- What is still open against the release, the PI funnel, and Feature readiness
  are `/rhdh-release-status`. That skill reports status; this one reports fit.
- Milestone dates, including Code Freeze and Feature Freeze, are
  `/rhdh-release-schedule`.
- Team name to Cloud ID and board is `/rhdh-release-teams`.
- Board IDs, JQL, Team-field traps, roster GraphQL, and the Greenhopper
  sprint-report seam are `/rhdh-jira-api`.
- What a T-shirt size means when writing an issue is `/rhdh-jira-authoring`.
  This skill does not use that sprint-effort table for demand. Unsized T-shirts
  use a placeholder Fibonacci map in the script until a calibrated conversion
  exists. Never treat the Size field's 1–5 as story points.

## Completion

Complete when both ledgers name the sample sprints, the remaining-sprint count
through Code Freeze (three-week slots unless the snapshot overrides
`sprint_days`), the meeting factor, and whether interrupt was retrieved; when
fillable planned capacity is shown separately from the interrupt reserve, and
required demand is fit against fillable rather than against mixed completed
work; when every candidate Feature is either estimated (Epic children, or a
T-shirt placeholder) or listed as unsized; when any T-shirt fallback ran, the
placeholder map is printed with the demand; and when stretch Features are
called out as first cuts. Report the JQL behind the sample and whether any
search was truncated. Say when story-point coverage is under 50% and the unit
switched to issue counts. Print the arithmetic so a 40% meeting haircut on
already-observed Jira velocity cannot hide. When interrupt was not retrieved,
say fillable is an upper bound and do not claim a 0% interrupt rate.
