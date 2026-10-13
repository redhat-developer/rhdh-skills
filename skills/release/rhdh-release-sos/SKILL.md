---
name: rhdh-release-sos
description: >-
  Builds the RHDH release check-in report for Scrum of Scrums with team leads —
  milestone calendar, timeline-aware checks from references/sos-checks.md, and
  Jira counts from the RHIDP Operational Rich Filter. Use for "SoS report for
  2.1.0", "scrum of scrums release status", "release check-in for team leads",
  or "what should we review before feature freeze".
compatibility: "Python 3.9+ and uv; /rhdh-release-status and /rhdh-release-schedule (install both beside this skill — the SoS CLI imports release-status scripts and fails if they are missing); acli with a Jira session; gog for engineering team Cloud IDs; an RHIDP Operational Rich Filter export."
---

# RHDH release SoS check-in

Produce the cumulative release check-in a Scrum of Scrums call needs: where the
release sits on the calendar, which checklist rows are due today, and the Jira
counts behind them. Read-only — the report is copied into the meeting; nothing is
posted.

## Route

Load `workflows/sos-report.md`. The runbook lives in `references/sos-checks.md`;
timeline rules in `references/timeline.md`; output shape in
`references/report-format.md`.

## Boundary with the neighbouring skills

- Milestone dates on their own — `/rhdh-release-schedule`.
- Ad-hoc counts without the SoS runbook — `/rhdh-release-status`.
- Team roster and Slack handles — `/rhdh-release-teams`.
- Slack freeze announcements — `/rhdh-release-announce`.
- Rich Filter setup prose — `/rhdh-release-status` (`references/config.md` there).

Query execution reuses the `/rhdh-release-status` scripts through
`scripts/_release_bridge.py`; install both skills together.

## Completion

Complete when the user receives `report_markdown` from the CLI unchanged in chat,
and a self-contained HTML file exists at `report_html_path` (written by every
`run`, not `plan`): metadata table, milestone table, Checks rows, and team
sub-rows as in the markdown report. Nothing was posted to Slack or Jira.
