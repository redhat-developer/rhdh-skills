---
name: rhdh-pr-triage
description: >-
  Triages open Renovate and Dependabot dependency PRs across RHDH
  repositories — rhdh-operator, rhdh-chart, rhdh-local, and rhdh-must-gather:
  lists, classifies by branch and release state, then approves, holds, unholds,
  merges, or closes per policy. Use for "triage renovate PRs", "review
  dependency PRs", "dependabot triage", "check bot PRs", or "renovate
  triage". For code-level review of a single PR, use /rhdh-pr-review. For
  overlay PR backlog triage, use /rhdh-overlay.
compatibility: "GitHub CLI and Python 3."
---

# RHDH Dependency PR Triage

Batch triage of Renovate and Dependabot PRs across RHDH repositories. Fetches,
classifies, decides, and executes per policy — or stops at the decision table
in dry-run mode.

## Route

Load `workflows/triage.md`.

When the user asks for a dry run ("dry run", "just show me", "what would
happen", "preview"), pass `--dry-run` to the script and tell the workflow to
stop after the decision table. No mutations are executed in dry-run mode.

## Boundary

- Code-level review of a single PR is `/rhdh-pr-review`.
- Overlay PR backlog triage is `/rhdh-overlay`.
- Release schedule lookups are `/rhdh-release-schedule`.
- Platform lifecycle checks are `/rhdh-platform-lifecycle`.

## Write gate

Invoke the named skill `mutation-gate` and follow it. Skipped entirely in
dry-run mode.

Each operation states its target repository and PR, the exact `gh` command,
a one-line preview of what it does, and recovery on failure.

## Completion

Complete when every open bot PR across the target repositories has been
classified and a decision assigned. In normal mode: the mutation-gate plan has
been approved, every operation reported its outcome (including skipped ones),
and a summary table is shown. In dry-run mode: the decision table and a summary
of planned actions are shown, and no mutations were executed.
