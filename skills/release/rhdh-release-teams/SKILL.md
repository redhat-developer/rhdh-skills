---
name: rhdh-release-teams
description: >-
  Resolves the RHDH team roster from the RHDH Team Mapping spreadsheet — team
  name, category, team ID, leads, Slack handles, and the Jira Cloud ID used in
  `"Team[Team]"` JQL clauses. Use for "who leads the Plugins team", "list RHDH
  teams", "which engineering teams are active", "Cloud ID for COPE", or "what is
  the Slack handle for the AI team lead".
compatibility: "Python 3.9+ and uv; gog for the RHDH Team Mapping spreadsheet; an RHIDP Operational Rich Filter export when authoritative Cloud IDs are needed."
---

# RHDH teams and leads

Answer who a team is, who leads it, and what identifier Jira knows it by.
Read-only.

## Route

Load `workflows/teams-and-leads.md`.

## Boundary with the neighbouring skills

- How many issues each team still has open against a release is
  `/rhdh-release-status`, whose per-team breakdown consumes the Cloud IDs this
  skill resolves.
- The freeze message that lists teams and pings their leads is
  `/rhdh-release-announce`.
- Assigning work to a person or team, or any Jira write, is `/rhdh-jira-update`.

## Completion

Complete when each team named in the answer carries its category, leads, Slack
handles, and Cloud ID as the source holds them, and the answer says whether the
Cloud IDs came from the Rich Filter export or from the spreadsheet column. Say
that inactive teams are excluded whenever the full roster was requested. A team
the user named that does not appear in the sheet is reported as absent, not
matched to the nearest similar name.
