---
name: rhdh-install-prepare-refinement
description: >-
  Prepares a signal-driven RHDH Install refinement briefing before ceremony:
  release window, clickable Jira slices aligned to Feature Planning / Team /
  Hygiene dashboards, and only non-zero attention signals. Deterministic scripts
  are zero-token; a required Noticed pass interprets cross-signal patterns from
  compact facts JSON. Use for "prepare refinement", "refinement briefing", "what
  needs attention before Install refinement", or RHIDP-16490 install ceremony prep.
  Read-only.
compatibility: >-
  Python 3.9+; Jira REST via JIRA_EMAIL/JIRA_API_TOKEN or .jira-token; one LLM
  step per references/noticed.md after the script. Does not duplicate jira-lint
  enforcement.
---

# Prepare RHDH Install refinement

Compress operational knowledge into **what needs attention before refinement** —
not a hygiene report and not a duplicate of `/rhdh-jira-refine`.

## Route

Load `workflows/prepare-refinement.md`. Run `scripts/prepare_refinement.py` with
`--facts-out`, then **always** run the ✨ Noticed step in `references/noticed.md`.

## UX contract

- **Signal-driven:** render a row only when `count > 0`; omit empty sections.
- **Expand exceptions:** `✅` section is a linked count only — no issue list.
- **Dashboard headings:** section titles link to JQL/filter slices (release
  candidate + team), with dashboard URLs where configured.
- **✨ Noticed:** required after the script; insert after the header, before
  signal sections. Omit the section body only when no cross-signal insight exists
  (see `references/noticed.md`).

## Neighbours

- Field hygiene automation and Slack DMs: **rhdh-jira-lint** (do not reimplement).
- Per-issue readiness / exit criteria: `/rhdh-jira-refine`.
- Release matrices: `/rhdh-release-status`.
- Sprint fill: `/rhdh-jira-sprint-plan`.

## Completion

1. Script exits 0; markdown and `--facts-out` JSON match the queue (live or fixture).
2. Noticed step executed; final briefing includes `## ✨ Noticed` when insight
   exists, inserted in the correct position.
