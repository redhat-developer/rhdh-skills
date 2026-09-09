---
name: rhdh-release-status
description: >-
  Reports what is still open against an RHDH release from Jira RHIDP, RHDHPLAN,
  RHDHBUGS, and RHDHSUPP: issue counts by type, blocker bugs, CVEs, Engineering
  EPICs, per-team breakdowns, release-note lifecycle, Post Code Freeze scope, and
  any query in the RHIDP Operational Rich Filter export. Also reports readiness at
  the Feature and Program Increment level: PI funnel, feature status matrix,
  stretch features, epic roll-up, cross-team dependency map, per-Feature coherence,
  and risk assessment. Use for "release status for 1.10", "what's blocking 1.10.3",
  "are we ready to ship 1.10", or "PI funnel for 2.1".
compatibility: "Python 3.9+ and uv; acli with a Jira session; gog for the per-team breakdown; an RHIDP Operational Rich Filter export for freeze, release-note, and Post Code Freeze scopes."
---

# RHDH release status

Answer "how is this release doing" with numbers that carry a Jira link and a
timestamp. Read-only: this skill never edits Jira and never posts anything.

## Route

Load `workflows/release-status.md`. It maps each question to the
`scripts/release.py` subcommand that answers it, and carries the two scope rules
the CLI output does not explain on its own.

For readiness at the Feature and Program Increment level rather than the issue
level — "are we ready to ship", PI funnel, dependency map, per-Feature coherence
— load `references/feature-readiness.md` instead. It runs quick mode for ceremony
prep and deep mode for full coherence analysis. Both are read-only.

## Rich Filter ownership

This skill owns the Rich Filter configuration prose. `references/config.md` holds
the spreadsheet IDs, the discovery rule, and the `RHDH_RICH_FILTER_PATH`
override; `references/rich-filter-coverage.md` records which release behaviours
come from the export and which JQL stays local and why. Another skill that hits
an unavailable Rich Filter template names `/rhdh-release-status` rather than
restating the setup.

## Boundary with the neighbouring skills

- Milestone dates — Feature Freeze, Code Freeze, GA — are `/rhdh-release-schedule`.
- Whether a named team can fit the `rhdh-X.Y-candidate` Features through Code
  Freeze is `/rhdh-release-capacity-plan`. This skill reports status, not fit.
- A Slack freeze announcement is `/rhdh-release-announce`.
- The team roster, leads, and Cloud IDs are `/rhdh-release-teams`. This skill
  counts issues per team; it does not publish the roster.
- Reading a single issue, a board, or a sprint is `/rhdh-jira-api`. Any Jira
  write is `/rhdh-jira-update`.

## Completion

Complete when every number in the answer names the subcommand or JQL that
produced it, states when it was read, and carries the Jira search link behind it.
A count the
CLI reported as truncated is reported as a floor, not a total. A field Jira could
not supply is listed as unverified — never carried over from an earlier release
or inferred from a neighbouring count. When the Rich Filter was unavailable, say
which scopes went unanswered instead of substituting a hand-written query.
