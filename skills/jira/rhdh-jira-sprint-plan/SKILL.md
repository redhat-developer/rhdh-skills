---
name: rhdh-jira-sprint-plan
description: >-
  Builds the planning package for an RHDH scrum team's next sprint from Jira
  RHIDP, RHDHPLAN, RHDHBUGS, and RHDHSUPP: carryover from the active sprint,
  three-sprint velocity, per-member capacity, the ready-for-planning queue,
  available capacity, suggested fill, critical customer bugs, and retro action
  items. Use for "plan the sprint", "sprint planning prep", "what's our capacity
  next sprint", "what can we commit to", or "what's carrying over". Works on a
  team and a sprint, not on one issue — a bare key such as RHIDP-1234 is not a
  sprint. Looks forward at the sprint that has not started; summarizing the one
  that just ended is a different job.
compatibility: "Authenticated read access to redhat.atlassian.net covering RHIDP, RHDHPLAN, RHDHBUGS and RHDHSUPP; ability to run a JQL search and read sprints and boards. A Jira team ID and board ID. Windows, macOS, Linux."
local-tooling: "Optional: a Jira session — acli, an Atlassian MCP server, or another tool."
---

# Plan an RHDH sprint

Produce the numbers a planning call needs, before the call. Read-only until the
team decides something.

## Goals, not tools

Every step below states its goal, never which tool to use. Use whichever tool
you actually have for Jira — an ADLC tool, an MCP server, or a CLI you know
how to drive. `/rhdh-jira-context` owns the JQL,
the field IDs, and the end-state rules that keep a silent failure from
becoming a wrong velocity number.

## Route

Load `workflows/plan-sprint.md`. Run it before each bi-weekly sprint planning
call.

## Boundary with the neighbouring skills

- The review of the sprint that just ended — committed versus completed,
  per-member results, demo checklist — is `/rhdh-jira-sprint-report`. This skill
  looks forward; that one looks back.
- Making the backlog worth planning from is `/rhdh-jira-refine`.
- Pre-refinement ceremony analysis and facilitator brief is
  `/rhdh-prepare-refinement`.
- Picking and setting an assignee is `/rhdh-jira-update`. This skill invokes it
  for fill suggestions rather than scoring assignees itself.
- Board IDs, sprint naming, JQL, and the Team field's JQL limitation are
  `/rhdh-jira-context`.
- Whether a team can fit `rhdh-X.Y-candidate` Features through Code Freeze is
  `/rhdh-release-capacity-plan`. This skill fills the next sprint only.
- Release-level readiness is `/rhdh-release-status`.

## Completion

Complete when velocity names the three sprints it averaged, carryover names every
issue counted, and available capacity shows the subtraction that produced it.
Report the JQL behind each number and whether any search was truncated. Say when
story-point coverage is too thin to trust a velocity figure rather than
publishing a number that looks solid. Fill suggestions are presented as
suggestions — team members self-select during planning, and nothing here assigns
anyone without approval.
