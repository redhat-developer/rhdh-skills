---
name: rhdh-install-prepare-refinement
description: >-
  Prepares a signal-driven RHDH Install refinement briefing before ceremony:
  release window, clickable Jira slices aligned to Feature Planning / Team /
  Hygiene dashboards, and only non-zero attention signals. Deterministic scripts
  are zero-token; an optional Noticed pass may interpret cross-signal patterns.
  Use for "prepare refinement", "refinement briefing", "what needs attention
  before Install refinement", or RHIDP-16490 install ceremony prep. Read-only.
compatibility: >-
  Python 3.9+; Jira REST via JIRA_EMAIL/JIRA_API_TOKEN or .jira-token; optional
  LLM only for references/noticed.md. Does not duplicate rhdh-jira-lint enforcement.
---

# Prepare RHDH Install refinement

Compress operational knowledge into **what needs attention before refinement** —
not a hygiene report and not a duplicate of `/rhdh-jira-refine`.

## Route

Load `workflows/prepare-refinement.md` and run `scripts/prepare_refinement.py`.

## UX contract

- **Signal-driven:** render a row only when `count > 0`; omit empty sections.
- **Expand exceptions:** `✅` section is a linked count only — no issue list.
- **Dashboard headings:** section titles link to JQL/filter slices (release
  candidate + team), with dashboard URLs where configured.
- **✨ Noticed:** optional; see `references/noticed.md`. Omit when there is no
  cross-signal insight.

## Neighbours

- Field hygiene automation and Slack DMs: **rhdh-jira-lint** (do not reimplement).
- Per-issue readiness / exit criteria: `/rhdh-jira-refine`.
- Release matrices: `/rhdh-release-status`.
- Sprint fill: `/rhdh-jira-sprint-plan`.

## Completion

Script exits 0 and prints markdown. Facts JSON lists `signals` and `overlaps` for
Noticed. Queue JQL and issue count match the live or fixture input.
