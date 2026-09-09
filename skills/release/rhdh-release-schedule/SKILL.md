---
name: rhdh-release-schedule
description: >-
  Gives the milestone dates for an RHDH version — Feature Freeze, Code Freeze,
  Docs Input Freeze, Docs Freeze, Go/No Go & Push, and GA announce — reading
  active releases from the RHDHPLAN release Feature in Jira and planned ones from
  the RHDH release schedule spreadsheet. Use for "when is code freeze for 1.11",
  "RHDH release dates", "GA date for 2.1", "what are the key dates for 1.10.3",
  or "has 1.10 passed feature freeze yet".
compatibility: "Python 3.9+ and uv; acli with a Jira session for active releases; gog for the release schedule spreadsheet."
---

# RHDH release dates

Say when a milestone falls, and say which source said so. Read-only.

## Route

Load `workflows/release-dates.md`. One workflow covers both sources: Jira for
releases already in flight, the schedule spreadsheet for anything further out.
Which one answers a given version is a lookup, not a decision the user makes.

## Boundary with the neighbouring skills

- What is still open against a release is `/rhdh-release-status`.
- Drafting the Slack message that goes out at a freeze is
  `/rhdh-release-announce`, which pulls the date it needs itself.
- Which OCP, AKS, EKS, GKE, or PostgreSQL versions a release supports, and when
  they go end-of-life, is `/rhdh-platform-lifecycle`. Product lifecycle is not a
  release milestone.
- Reading or editing the RHDHPLAN release Feature as a Jira issue is
  `/rhdh-jira-api`.
- Ensuring the fix version for a release exists on RHIDP, RHDHPLAN, and
  RHDHBUGS is `/rhdh-release-fixversions`.

## Completion

Complete when every date reported names its source — the Jira release issue key
or the schedule spreadsheet tab — and dates the two sources disagree on are shown
side by side rather than silently reconciled. A milestone the source records as
TBD is reported as TBD, never estimated from the surrounding dates or from a
previous release's spacing. When a version appears in neither source, say so and
ask for the exact version string as it appears in the sheet.
