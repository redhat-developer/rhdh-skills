---
name: rhdh-install-prepare-refinement
description: >-
  Prepares a signal-driven RHDH Install refinement briefing before ceremony:
  release window, clickable Jira slices aligned to Feature Planning / Team /
  Hygiene dashboards, and only non-zero attention signals. Deterministic scripts
  are zero-token, including deterministic ✨ Noticed from cross-signal facts.
  Use for "prepare refinement", "refinement briefing", "what needs attention
  before Install refinement", or RHIDP-16490 install ceremony prep. Read-only.
compatibility: >-
  Python 3.9+; Jira REST via JIRA_EMAIL/JIRA_API_TOKEN or .jira-token. Optional
  agent pass per references/noticed.md for richer Noticed. Does not duplicate
  jira-lint enforcement.
---

# Prepare RHDH Install refinement

Compress operational knowledge into **what needs attention before refinement** —
not a hygiene report and not a duplicate of `/rhdh-jira-refine`.

## Route

Load `workflows/prepare-refinement.md`. From repo root run
`./scripts/prepare-install-refinement` — stdout is the full briefing including
✨ Noticed. Agents may extend Noticed via `references/noticed.md` and the facts JSON.

## UX contract

- **Signal-driven:** render a row only when `count > 0`; omit empty sections.
- **Expand exceptions:** `✅` section is a linked count only — no issue list.
- **Dashboard headings:** section titles link to JQL/filter slices (release
  candidate + team), with dashboard URLs where configured.
- **✨ Noticed:** emitted by the script after the header, before signal sections;
  omitted when no cross-signal insight exists (see `scripts/_noticed.py`).

## Neighbours

- Field hygiene automation and Slack DMs: **rhdh-jira-lint** (do not reimplement).
- Per-issue readiness / exit criteria: `/rhdh-jira-refine`.
- Release matrices: `/rhdh-release-status`.
- Sprint fill: `/rhdh-jira-sprint-plan`.

## Completion

1. Script exits 0; markdown includes ✨ Noticed when applicable; facts JSON matches
   the queue (live or fixture).
